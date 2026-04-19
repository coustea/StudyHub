"""文件服务：上传路径解析、文件内容读取、文档分析。

供 chat、avatar 等需要处理用户上传文件的模块共享。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage

from app.infra.logging import get_logger
from app.shared.paths import WORKPLACE_DIR

logger = get_logger(__name__)

UPLOAD_DIR = WORKPLACE_DIR / "chat-uploads"
MAX_FILE_CONTENT_CHARS = 15000


def resolve_uploaded_path(file_url: str) -> tuple[int, str] | None:
    """将 URL 路径解析为 (owner_id, absolute_path)，校验路径安全性和文件存在性。"""
    relative: str
    if file_url.startswith("/api/v1/ai/chat/uploads/"):
        relative = file_url.removeprefix("/api/v1/ai/chat/uploads/")
    elif file_url.startswith("/uploads/"):
        relative = file_url.removeprefix("/uploads/")
    else:
        # 支持直接传本地绝对路径（chat-uploads/<user>/<session>/<file>）
        try:
            local_path = Path(file_url).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        upload_root = UPLOAD_DIR.resolve()
        if not str(local_path).startswith(str(upload_root)):
            return None
        if not local_path.exists():
            return None
        relative_parts = local_path.relative_to(upload_root).parts
        if len(relative_parts) == 3:
            owner_part, session_id, filename = relative_parts
        elif len(relative_parts) == 2:
            owner_part, filename = relative_parts
            session_id = ""
        else:
            return None
        if not owner_part.isdigit():
            return None
        if session_id and Path(session_id).name != session_id:
            return None
        if Path(filename).name != filename:
            return None
        return int(owner_part), str(local_path)

    parts = [p for p in relative.split("/") if p]
    if len(parts) == 3:
        owner_part, session_id, filename = parts
    elif len(parts) == 2:
        owner_part, filename = parts
        session_id = ""
    else:
        return None

    if not owner_part.isdigit():
        return None
    if session_id and Path(session_id).name != session_id:
        return None
    if Path(filename).name != filename:
        return None

    user_dir = (UPLOAD_DIR / owner_part).resolve()
    path = (user_dir / session_id / filename).resolve() if session_id else (user_dir / filename).resolve()
    if not str(path).startswith(str(user_dir)):
        return None
    if not path.exists():
        return None

    return int(owner_part), str(path)


def resolve_uploaded_image_path(image_url: str) -> Path | None:
    """解析图片 URL 为本地 Path，返回 None 表示无效路径。"""
    resolved = resolve_uploaded_path(image_url)
    if resolved is None:
        return None
    _, absolute_path = resolved
    path = Path(absolute_path)
    return path if path.is_file() else None


def read_uploaded_file_content(absolute_path: str) -> str:
    """读取上传文件内容，支持 .pdf / .docx / .txt / .md / .log。"""
    path = Path(absolute_path)
    if not path.exists():
        return f"文件不存在: {absolute_path}"
    if not path.is_file():
        return f"路径不是文件: {absolute_path}"

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pymupdf import open as pdf_open

        text_parts = []
        with pdf_open(str(path)) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        content = "\n".join(text_parts)
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        content = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    elif suffix in {".txt", ".md", ".log"}:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        return f"不支持的文件类型: {suffix}（支持: .pdf, .docx, .txt, .md, .log）"

    if not content or not content.strip():
        return "文件内容为空"
    if len(content) > MAX_FILE_CONTENT_CHARS:
        content = content[:MAX_FILE_CONTENT_CHARS] + "\n\n[...文档内容过长，已截断...]"
    return content


async def analyze_documents(*, current_user_id: int, file_urls: list[str], question: str) -> dict:
    """批量读取用户上传的文档内容，返回分析摘要。"""
    documents: list[dict[str, str]] = []
    snippets: list[str] = []

    for file_url in file_urls:
        resolved = resolve_uploaded_path(file_url)
        if resolved is None:
            logger.warning("[DocumentAnalysis] failed to resolve %s", file_url)
            continue

        owner_id, absolute_path = resolved
        if owner_id != current_user_id:
            logger.warning(
                "[DocumentAnalysis] forbidden file access user=%s owner=%s",
                current_user_id, owner_id,
            )
            continue

        content = read_uploaded_file_content(absolute_path)
        documents.append({
            "url": file_url,
            "name": Path(absolute_path).name,
            "absolute_path": absolute_path,
            "content": content,
        })
        snippets.append(f"文件《{Path(absolute_path).name}》内容如下：\n{content}")

    if not documents:
        return {
            "success": False,
            "documents": [],
            "analysis_text": "未能读取可分析的文档内容。",
            "error": "未找到可访问的文档。",
        }

    analysis_text = (
        f"用户问题：{question or '请分析这些文档'}\n\n"
        "以下是已提取的文档内容，请基于它们回答用户问题，并在回答中尽量提炼知识点：\n\n"
        + "\n\n".join(snippets)
    )
    return {
        "success": True,
        "documents": documents,
        "analysis_text": analysis_text,
        "error": None,
    }