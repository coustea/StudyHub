"""Chat application service boundary.

集中保留 chat 的应用层编排，明确主链路为：api -> service -> agent
- 文件/图片处理接口（含保护机制）
- ConversationStore: 会话/历史持久化
- ChatUseCases: 路由入口与 agent 调用
- get_chat_usecases: 模块装配

通用服务已提取到 app/shared/：
- request_context: ContextVar 请求上下文
- agent_context: AgentContextService（记忆/画像/上下文构建）
- vision: VisionService（图片分析）
- file_service: 文件路径解析、内容读取
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

# ---- 通用服务（从 shared 导入） ----
from app.shared.request_context import (
    runtime_context as chat_runtime_context,
    get_current_user_id,
    get_current_session_id,
    set_user_id,
    set_session_id,
)
from app.shared.agent_context import AgentContextService
from app.shared.vision import build_vision_service
from app.shared.file_service import (
    resolve_uploaded_path,
    resolve_uploaded_image_path,
    read_uploaded_file_content,
)

from app.chat.utils import truncate
from app.infra.llm import get_glm_vision_llm
from app.infra.logging import get_logger
from app.memory.short_term import short_term_service
from app.memory.session import session_service
from app.shared.storage import local_file_store

from app.chat.schemas import AttachmentInfo, ChatMessageItem, ToolCallRecord

CHAT_MODULE_NAME = "mentor"

logger = get_logger(__name__)
MAX_FILE_CONTENT_CHARS = 15000
MAX_ANALYZE_FILE_COUNT = 8
MAX_ANALYZE_TOTAL_CHARS = 40000
MAX_PDF_PAGES_TO_READ = 80
MAX_DOCX_PARAGRAPHS_TO_READ = 1200
MAX_IMAGE_ANALYZE_COUNT = 8
MAX_UPLOAD_FILES_PER_REQUEST = 12
AVATAR_MODULE_NAME = "avatar"


# ---------------------------------------------------------------------------
# ChatContextService: AgentContextService 的 chat 模块特化
# ---------------------------------------------------------------------------

class ChatContextService(AgentContextService):
    """Chat 模块上下文服务，继承通用 AgentContextService，固定 module_name="mentor"。"""

    def __init__(self) -> None:
        super().__init__(module_name=CHAT_MODULE_NAME)


# ---------------------------------------------------------------------------
# SSE 编码
# ---------------------------------------------------------------------------

def format_sse(event: str, data: Any) -> str:
    """Encode a single SSE frame."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    lines = payload.splitlines() or [""]
    body = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{body}\n\n"


# ---------------------------------------------------------------------------
# 增强文件读取（带保护机制的版本，chat 模块专用）
# ---------------------------------------------------------------------------

def read_uploaded_file_content_with_meta(absolute_path: str) -> dict[str, Any]:
    """读取上传文档内容并返回保护机制元数据（页数/段落/长度截断提示）。"""
    path = Path(absolute_path)
    if not path.exists():
        return {
            "success": False,
            "content": f"文件不存在: {absolute_path}",
            "notes": [],
        }
    if not path.is_file():
        return {
            "success": False,
            "content": f"路径不是文件: {absolute_path}",
            "notes": [],
        }

    notes: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pymupdf import open as pdf_open

        text_parts = []
        with pdf_open(str(path)) as doc:
            total_pages = len(doc)
            pages_to_read = min(total_pages, MAX_PDF_PAGES_TO_READ)
            for idx in range(pages_to_read):
                text_parts.append(doc[idx].get_text())
            if total_pages > MAX_PDF_PAGES_TO_READ:
                notes.append(f"PDF 共 {total_pages} 页，为保护性能仅分析前 {MAX_PDF_PAGES_TO_READ} 页。")
        content = "\n".join(text_parts)
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        total_paragraphs = len(paragraphs)
        if total_paragraphs > MAX_DOCX_PARAGRAPHS_TO_READ:
            notes.append(
                f"DOCX 共 {total_paragraphs} 个段落，为保护性能仅分析前 {MAX_DOCX_PARAGRAPHS_TO_READ} 个段落。"
            )
        content = "\n".join(paragraphs[:MAX_DOCX_PARAGRAPHS_TO_READ])
    elif suffix in {".txt", ".md", ".log"}:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        return {
            "success": False,
            "content": f"不支持的文件类型: {suffix}（支持: .pdf, .docx, .txt, .md, .log）",
            "notes": [],
        }

    if not content or not content.strip():
        return {
            "success": True,
            "content": "文件内容为空",
            "notes": notes,
        }
    if len(content) > MAX_FILE_CONTENT_CHARS:
        content = content[:MAX_FILE_CONTENT_CHARS] + "\n\n[...文档内容过长，已截断...]"
        notes.append(f"文档文本超过 {MAX_FILE_CONTENT_CHARS} 字符，已截断。")
    return {
        "success": True,
        "content": content,
        "notes": notes,
    }


async def analyze_documents(*, current_user_id: int, file_urls: list[str], question: str) -> dict:
    """批量读取用户上传的文档内容（含保护机制），返回分析摘要。"""
    documents: list[dict[str, str]] = []
    snippets: list[str] = []
    notices: list[str] = []
    remaining_chars = MAX_ANALYZE_TOTAL_CHARS
    limited_file_urls = (file_urls or [])[:MAX_ANALYZE_FILE_COUNT]
    if len(file_urls or []) > MAX_ANALYZE_FILE_COUNT:
        notices.append(
            f"本次上传文档 {len(file_urls)} 个，为保护性能仅分析前 {MAX_ANALYZE_FILE_COUNT} 个文档。"
        )

    for file_url in limited_file_urls:
        if remaining_chars <= 0:
            notices.append("已达到本轮分析内容上限，后续文档将不再展开解析。")
            break
        resolved = resolve_uploaded_path(file_url)
        if resolved is None:
            logger.warning("[DocumentAnalysis] failed to resolve %s", file_url)
            continue

        owner_id, absolute_path = resolved
        if owner_id != current_user_id:
            logger.warning("[DocumentAnalysis] forbidden file access user=%s owner=%s", current_user_id, owner_id)
            continue

        content_payload = read_uploaded_file_content_with_meta(absolute_path)
        content = str(content_payload.get("content", ""))
        note_items = [str(item) for item in (content_payload.get("notes") or []) if str(item).strip()]
        notices.extend(note_items)

        if len(content) > remaining_chars:
            content = content[:remaining_chars] + "\n\n[...超出本轮分析内容预算，已截断...]"
            notices.append(f"分析总文本已达到 {MAX_ANALYZE_TOTAL_CHARS} 字符上限，后续内容已截断。")
        remaining_chars = max(0, remaining_chars - len(content))

        documents.append({
            "url": file_url,
            "name": Path(absolute_path).name,
            "absolute_path": absolute_path,
            "content": content,
        })
        note_text = f"\n[保护提示] {'; '.join(note_items)}" if note_items else ""
        snippets.append(f"文件《{Path(absolute_path).name}》内容如下：\n{content}{note_text}")

    if not documents:
        return {
            "success": False,
            "documents": [],
            "analysis_text": "未能读取可分析的文档内容。",
            "error": "未找到可访问的文档。",
            "notices": notices,
        }

    notice_prefix = ""
    if notices:
        uniq_notices = list(dict.fromkeys(notices))
        notice_prefix = "分析保护提示：\n" + "\n".join(f"- {msg}" for msg in uniq_notices) + "\n\n"
    analysis_text = (
        f"用户问题：{question or '请分析这些文档'}\n\n"
        + notice_prefix
        + "以下是已提取的文档内容，请基于它们回答用户问题，并在回答中尽量提炼知识点：\n\n"
        + "\n\n".join(snippets)
    )
    return {
        "success": True,
        "documents": documents,
        "analysis_text": analysis_text,
        "error": None,
        "notices": list(dict.fromkeys(notices)),
    }


def _build_attachment_analysis_context(
    *,
    image_result: dict[str, Any] | None,
    document_result: dict[str, Any] | None,
) -> str:
    sections: list[str] = []

    if isinstance(image_result, dict):
        image_text = str(image_result.get("analysis_text", "")).strip()
        if image_text:
            mode = str(image_result.get("mode", "unknown")).strip() or "unknown"
            sections.append(f"### 图片预分析（mode={mode}）\n{image_text}")

    if isinstance(document_result, dict):
        doc_text = str(document_result.get("analysis_text", "")).strip()
        if doc_text:
            sections.append(f"### 文档预分析\n{doc_text}")

    if not sections:
        return ""
    return truncate("\n\n".join(sections), 8000)


async def analyze_attachments_parallel(
    *,
    current_user_id: int,
    image_urls: list[str],
    file_urls: list[str],
    question: str,
    vision_service: "VisionService",
) -> dict[str, Any]:
    """并行分析附件（图片 + 文档），返回结构化结果与可注入上下文。"""
    image_urls = image_urls or []
    file_urls = file_urls or []
    notices: list[str] = []

    if len(image_urls) > MAX_IMAGE_ANALYZE_COUNT:
        notices.append(f"本次上传图片 {len(image_urls)} 张，为保护性能仅分析前 {MAX_IMAGE_ANALYZE_COUNT} 张。")
        image_urls = image_urls[:MAX_IMAGE_ANALYZE_COUNT]

    result: dict[str, Any] = {
        "success": False,
        "image": None,
        "document": None,
        "analysis_context": "",
        "notices": notices,
    }
    if not image_urls and not file_urls:
        return result

    tasks: list[asyncio.Task] = []
    slots: list[str] = []

    if image_urls:
        tasks.append(asyncio.create_task(vision_service.analyze_images(image_urls, question)))
        slots.append("image")
    if file_urls:
        tasks.append(
            asyncio.create_task(
                analyze_documents(
                    current_user_id=current_user_id,
                    file_urls=file_urls,
                    question=question,
                )
            )
        )
        slots.append("document")

    done = await asyncio.gather(*tasks, return_exceptions=True)
    for slot, payload in zip(slots, done):
        if isinstance(payload, Exception):
            logger.exception("[AttachmentAnalysis] %s analyze failed", slot)
            result[slot] = {
                "success": False,
                "analysis_text": "",
                "error": str(payload),
            }
            continue
        result[slot] = payload

    image_result = result.get("image")
    document_result = result.get("document")
    result["analysis_context"] = _build_attachment_analysis_context(
        image_result=image_result if isinstance(image_result, dict) else None,
        document_result=document_result if isinstance(document_result, dict) else None,
    )
    if notices:
        notice_block = "### 附件分析保护提示\n" + "\n".join(f"- {msg}" for msg in notices)
        result["analysis_context"] = (
            f"{notice_block}\n\n{result['analysis_context']}" if result["analysis_context"] else notice_block
        )
    result["success"] = bool(result["analysis_context"])
    return result


# ---------------------------------------------------------------------------
# 会话与历史持久化
# ---------------------------------------------------------------------------

class ConversationStore:
    """对话会话与历史持久化。"""

    async def list_sessions(self, user_id: int, limit: int = 30, module_name: str = CHAT_MODULE_NAME) -> list[dict]:
        sessions = await session_service.get_user_chat_sessions(
            user_id=user_id,
            module=module_name,
            limit=limit,
        )
        return [{"id": s.id, "title": s.title, "updated_at": s.updated_at} for s in sessions]

    async def create_session(
        self,
        user_id: int,
        title: str = "新对话",
        module_name: str = CHAT_MODULE_NAME,
    ) -> dict:
        session = await session_service.create_chat_session(
            user_id=user_id,
            module=module_name,
            title=title,
        )
        return {"id": session.id, "title": session.title}

    async def archive_session(self, user_id: int, session_id: str, module_name: str = CHAT_MODULE_NAME) -> bool:
        del module_name
        return await session_service.archive_chat_session(session_id, user_id)

    async def get_history(
        self,
        *,
        user_id: int,
        session_id: str | None = None,
        limit: int = 50,
        module_name: str = CHAT_MODULE_NAME,
    ) -> list[ChatMessageItem]:
        target_session = session_id
        if not target_session:
            sessions = await session_service.get_user_chat_sessions(
                user_id=user_id,
                module=module_name,
                limit=1,
            )
            if not sessions:
                return []
            target_session = sessions[0].id

        messages = await short_term_service.get_recent_messages(
            user_id=user_id,
            session_id=target_session,
            module=module_name,
            limit=limit,
        )

        items: list[ChatMessageItem] = []
        for msg in messages:
            attachments = None
            if msg.attachments:
                try:
                    attachments = [AttachmentInfo(**v) for v in json.loads(msg.attachments)]
                except (json.JSONDecodeError, TypeError):
                    attachments = None

            tool_calls = None
            if msg.tool_calls:
                try:
                    tool_calls = [ToolCallRecord(**v) for v in json.loads(msg.tool_calls)]
                except (json.JSONDecodeError, TypeError):
                    tool_calls = None

            items.append(
                ChatMessageItem(
                    role=msg.role,
                    content=msg.content,
                    attachments=attachments,
                    tool_calls=tool_calls,
                    created_at=msg.created_at,
                )
            )
        return items


# ---------------------------------------------------------------------------
# Chat 用例入口
# ---------------------------------------------------------------------------

class ChatUseCases:
    """路由层可调用的 chat 应用入口。"""

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        file_store=local_file_store,
        module_name: str = CHAT_MODULE_NAME,
        default_session_suffix: str | None = None,
        stream_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.conversation_store = conversation_store
        self.file_store = file_store
        self.module_name = module_name
        self.default_session_suffix = default_session_suffix or module_name
        self._stream_runner = stream_runner

    def default_session_id(self, user_id: int) -> str:
        return f"user-{user_id}-default-{self.default_session_suffix}"

    @staticmethod
    def _default_tutor_stream_runner() -> Callable[..., Any]:
        # Delay import to avoid the service <-> agent circular import at module load time.
        from app.chat.agent import TutorAgent

        agent = TutorAgent.get_shared()
        return agent.chat_stream

    async def _build_attachment_analysis(
        self,
        *,
        user_id: int,
        session_id: str,
        user_message: str,
        image_urls: list[str],
        file_urls: list[str],
        attachment_analysis: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if attachment_analysis is not None:
            return attachment_analysis

        if not image_urls and not file_urls:
            return None

        try:
            vision_service = build_vision_service(get_glm_vision_llm())
            built = await analyze_attachments_parallel(
                current_user_id=user_id,
                image_urls=image_urls,
                file_urls=file_urls,
                question=user_message,
                vision_service=vision_service,
            )
            logger.info(
                "[ChatUseCases] 附件并行预分析完成 module=%s user=%s session=%s has_image=%s has_doc=%s has_context=%s",
                self.module_name,
                user_id,
                session_id,
                bool(image_urls),
                bool(file_urls),
                bool((built or {}).get("analysis_context")),
            )
            return built
        except Exception:
            logger.exception(
                "[ChatUseCases] 附件并行预分析失败 module=%s user=%s session=%s",
                self.module_name,
                user_id,
                session_id,
            )
            return None

    async def stream_chat_events(
        self,
        *,
        user_id: int,
        user_message: str,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        file_urls: list[str] | None = None,
        attachment_analysis: dict[str, Any] | None = None,
        stream_runner: Callable[..., Any] | None = None,
        input_source: str | None = None,
    ):
        effective_session = session_id or self.default_session_id(user_id)
        merged_image_urls = list(dict.fromkeys(image_urls or []))
        merged_file_urls = list(dict.fromkeys(file_urls or []))
        prepared_attachment_analysis = await self._build_attachment_analysis(
            user_id=user_id,
            session_id=effective_session,
            user_message=user_message,
            image_urls=merged_image_urls,
            file_urls=merged_file_urls,
            attachment_analysis=attachment_analysis,
        )

        runner = stream_runner or self._stream_runner or self._default_tutor_stream_runner()

        kwargs: dict[str, Any] = {
            "user_id": user_id,
            "user_message": user_message,
            "session_id": effective_session,
            "image_urls": merged_image_urls,
            "file_urls": merged_file_urls,
            "attachment_analysis": prepared_attachment_analysis,
        }
        if input_source is not None:
            kwargs["input_source"] = input_source

        with chat_runtime_context(user_id, effective_session):
            async for event in runner(**kwargs):
                if isinstance(event, dict):
                    if "event" in event and "data" in event:
                        yield event
                        continue
                    if "type" in event:
                        normalized_data = event.get("data")
                        if normalized_data is None and "content" in event:
                            normalized_data = event.get("content")
                        if normalized_data is None and "full_response" in event:
                            normalized_data = {"full_response": event.get("full_response", "")}
                        if normalized_data is None:
                            normalized_data = ""
                        yield {"event": str(event.get("type")), "data": normalized_data}
                        continue

                yield {"event": "message", "data": event}

    async def prepare_uploads(
        self,
        *,
        files: list[tuple[str, bytes]],
        user_id: int,
        session_id: str | None = None,
    ) -> tuple[str, list[str], list[str]]:
        if len(files) > MAX_UPLOAD_FILES_PER_REQUEST:
            raise ValueError(f"单次最多上传 {MAX_UPLOAD_FILES_PER_REQUEST} 个文件，请分批上传。")
        effective_session = session_id or self.default_session_id(user_id)
        image_urls: list[str] = []
        file_urls: list[str] = []

        for filename, content in files:
            if not filename:
                raise ValueError("文件名不能为空")
            saved = await self.save_upload(
                filename=filename,
                content=content,
                user_id=user_id,
                session_id=effective_session,
            )
            if saved["file_type"] == "image":
                image_urls.append(saved["url"])
            else:
                file_urls.append(saved["url"])

        return effective_session, image_urls, file_urls

    async def analyze_uploaded_attachments(
        self,
        *,
        user_id: int,
        question: str,
        session_id: str | None = None,
        files: list[tuple[str, bytes]] | None = None,
        image_urls: list[str] | None = None,
        file_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """上传并并行分析附件，返回可复用的分析结果。"""
        upload_payloads = files or []
        effective_session = session_id or self.default_session_id(user_id)

        uploaded_image_urls: list[str] = []
        uploaded_file_urls: list[str] = []
        if upload_payloads:
            (
                effective_session,
                uploaded_image_urls,
                uploaded_file_urls,
            ) = await self.prepare_uploads(
                files=upload_payloads,
                user_id=user_id,
                session_id=effective_session,
            )

        merged_image_urls = list(dict.fromkeys(uploaded_image_urls + list(image_urls or [])))
        merged_file_urls = list(dict.fromkeys(uploaded_file_urls + list(file_urls or [])))

        attachment_analysis = await self._build_attachment_analysis(
            user_id=user_id,
            session_id=effective_session,
            user_message=question,
            image_urls=merged_image_urls,
            file_urls=merged_file_urls,
            attachment_analysis=None,
        )
        return {
            "session_id": effective_session,
            "uploaded_image_urls": uploaded_image_urls,
            "uploaded_file_urls": uploaded_file_urls,
            "image_urls": merged_image_urls,
            "file_urls": merged_file_urls,
            "attachment_analysis": attachment_analysis or {
                "success": False,
                "image": None,
                "document": None,
                "analysis_context": "",
                "notices": [],
            },
        }

    async def stream_chat(
        self,
        *,
        user_id: int,
        user_message: str,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        file_urls: list[str] | None = None,
        attachment_analysis: dict[str, Any] | None = None,
        stream_runner: Callable[..., Any] | None = None,
        input_source: str | None = None,
    ):
        async for event in self.stream_chat_events(
            user_id=user_id,
            user_message=user_message,
            session_id=session_id,
            image_urls=image_urls,
            file_urls=file_urls,
            attachment_analysis=attachment_analysis,
            stream_runner=stream_runner,
            input_source=input_source,
        ):
            yield format_sse(event["event"], event["data"])

    async def save_upload(
        self,
        *,
        filename: str,
        content: bytes,
        user_id: int,
        session_id: str,
    ) -> dict:
        return await self.file_store.save_upload(
            filename=filename,
            content=content,
            user_id=user_id,
            session_id=session_id,
        )

    def resolve_uploaded_file(
        self,
        *,
        current_user_id: int,
        owner_id: int,
        session_id: str,
        filename: str,
    ):
        return self.file_store.resolve_user_file(
            current_user_id=current_user_id,
            owner_id=owner_id,
            session_id=session_id,
            filename=filename,
        )

    async def list_sessions(self, user_id: int, limit: int = 20) -> list[dict]:
        return await self.conversation_store.list_sessions(user_id, limit, module_name=self.module_name)

    async def create_session(self, user_id: int, title: str = "新对话") -> dict:
        return await self.conversation_store.create_session(user_id, title, module_name=self.module_name)

    async def archive_session(self, user_id: int, session_id: str) -> bool:
        return await self.conversation_store.archive_session(user_id, session_id, module_name=self.module_name)

    async def get_history(
        self,
        *,
        user_id: int,
        session_id: str | None = None,
        limit: int = 50,
    ):
        return await self.conversation_store.get_history(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
            module_name=self.module_name,
        )


# ---------------------------------------------------------------------------
# 模块装配
# ---------------------------------------------------------------------------

conversation_store = ConversationStore()
chat_usecases: ChatUseCases | None = None
avatar_chat_usecases: ChatUseCases | None = None


def get_chat_usecases() -> ChatUseCases:
    global chat_usecases
    if chat_usecases is None:
        chat_usecases = ChatUseCases(
            conversation_store=conversation_store,
            module_name=CHAT_MODULE_NAME,
            default_session_suffix=CHAT_MODULE_NAME,
        )
    return chat_usecases


def get_avatar_chat_usecases() -> ChatUseCases:
    global avatar_chat_usecases
    if avatar_chat_usecases is None:
        avatar_chat_usecases = ChatUseCases(
            conversation_store=conversation_store,
            module_name=AVATAR_MODULE_NAME,
            default_session_suffix=AVATAR_MODULE_NAME,
        )
    return avatar_chat_usecases


__all__ = [
    "CHAT_MODULE_NAME",
    "ChatContextService",
    "ChatUseCases",
    "ConversationStore",
    "chat_runtime_context",
    "chat_usecases",
    "conversation_store",
    "format_sse",
    "get_avatar_chat_usecases",
    "get_chat_usecases",
    "get_current_user_id",
    "get_current_session_id",
    "set_user_id",
    "set_session_id",
    "resolve_uploaded_path",
    "resolve_uploaded_image_path",
    "read_uploaded_file_content",
    "read_uploaded_file_content_with_meta",
    "analyze_documents",
    "analyze_attachments_parallel",
    "build_vision_service",
]
