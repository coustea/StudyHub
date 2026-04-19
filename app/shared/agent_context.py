"""Agent 上下文服务：通用化的记忆、画像、上下文构建。

从 ChatContextService 提取，通过 module_name 参数适配不同模块（chat / avatar）。
任何需要记忆管理、画像构建、上下文构建的 Agent 都可以复用此服务。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage

from app.chat.utils import normalize_message_content, truncate
from app.chat.schemas import ToolCallDetail
from app.config import PROFILE_GATE_EVERY_N_ASSISTANT_TURNS
from app.infra.logging import get_logger
from app.memory.service import (
    MEMORY_COMPRESSION_TOKEN_THRESHOLD,
    MEMORY_EXTRACTION_TOKEN_THRESHOLD,
    memory_service,
)
from app.memory.memory_types import (
    MEMORY_TYPE_BACKGROUND,
    MEMORY_TYPE_FACT,
    MEMORY_TYPE_GOAL,
    MEMORY_TYPE_PREFERENCE,
    MEMORY_TYPE_WEAKNESS,
)
from app.shared.file_service import resolve_uploaded_path

logger = get_logger(__name__)


class AgentContextService:
    """通用 Agent 上下文服务。

    负责：
    - 三层上下文构建（画像 → 记忆 → 对话历史）
    - 消息持久化
    - 后台记忆管道（事实提取、画像更新、记忆压缩）
    - 工具记录持久化

    Agent 只负责工作流决策，记忆 CRUD 全部委托给此服务。
    """

    def __init__(self, *, module_name: str) -> None:
        self.memory = memory_service
        self.fact_agent = _build_fact_agent()
        self.profile_agent = _build_profile_agent()
        self.module_name = module_name

    # ------------------------------------------------------------------
    # 消息持久化
    # ------------------------------------------------------------------
    async def save_message(
        self,
        *,
        user_id: int,
        session_id: str,
        role: str,
        content: str,
        attachments: str | None = None,
        tool_calls: str | None = None,
    ) -> None:
        """保存一条消息到数据库。"""
        await self.memory.save_message(
            user_id=user_id,
            session_id=session_id,
            module=self.module_name,
            role=role,
            content=content,
            attachments=attachments,
            tool_calls=tool_calls,
        )

    # ------------------------------------------------------------------
    # 上下文构建
    # ------------------------------------------------------------------
    async def build_profile_ctx(self, user_id: int) -> str:
        """构建用户画像上下文文本。"""
        profile = await self.memory.get_user_profile(user_id)
        if not profile:
            logger.debug("[%s] 画像上下文 user=%s 状态=空", self.module_name, user_id)
            return "暂无画像信息（新用户），请直接开始对话。"
        profile_dict = profile.model_dump(exclude_unset=True, exclude={"updated_at", "created_at"})
        if not profile_dict:
            logger.debug("[%s] 画像上下文 user=%s 状态=空字典", self.module_name, user_id)
            return "暂无画像信息（新用户），请直接开始对话。"
        logger.debug("[%s] 画像上下文 user=%s 字段=%s", self.module_name, user_id, list(profile_dict.keys()))
        return "\n".join(f"- {k}: {v}" for k, v in profile_dict.items() if v)

    async def build_memory_ctx(self, user_id: int) -> str:
        """构建长期记忆上下文文本。"""
        memories_by_type = await self.memory.get_user_context_memories(user_id=user_id)
        titles = {
            MEMORY_TYPE_PREFERENCE: "偏好",
            MEMORY_TYPE_GOAL: "目标",
            MEMORY_TYPE_WEAKNESS: "薄弱点",
            MEMORY_TYPE_FACT: "稳定事实",
            MEMORY_TYPE_BACKGROUND: "背景信息",
        }
        chunks: list[str] = []
        for mtype, title in titles.items():
            items = memories_by_type.get(mtype, [])
            if not items:
                continue
            lines = "\n".join(f"- {m.content}" for m in items)
            chunks.append(f"### {title}\n{lines}")

        if not chunks:
            logger.debug("[%s] 记忆上下文 user=%s 状态=空", self.module_name, user_id)
            return "暂无特定事实记忆。"

        logger.debug(
            "[%s] 记忆上下文 user=%s 类型=%s",
            self.module_name, user_id, [k for k, v in memories_by_type.items() if v],
        )
        return "\n\n".join(chunks)

    async def build_chat_ctx(
        self,
        user_id: int,
        session_id: str,
        user_message: str,
        image_urls: Optional[list[str]],
        file_urls: Optional[list[str]],
    ) -> tuple[list[AnyMessage], str]:
        """构建对话历史上下文，返回 (消息列表, 近期对话摘要文本)。"""
        initial_messages: list[AnyMessage] = []
        recent_lines: list[str] = []

        recent_msgs = await self.memory.get_recent_messages(
            user_id, session_id, self.module_name, limit=10,
        )
        for msg in recent_msgs[:-1]:
            if msg.role == "user":
                initial_messages.append(HumanMessage(content=msg.content))
                recent_lines.append(f"- 用户: {msg.content}")
            elif msg.role == "assistant":
                initial_messages.append(AIMessage(content=msg.content))
                recent_lines.append(f"- 助手: {msg.content}")

        content = user_message
        if image_urls:
            content += f"\n[Attached Images: {', '.join(image_urls)}]"
        if file_urls:
            content += f"\n[Attached Files: {', '.join(file_urls)}]"
        initial_messages.append(HumanMessage(content=content))

        logger.debug(
            "[%s] 对话上下文 user=%s session=%s 历史数=%s",
            self.module_name, user_id, session_id, len(initial_messages),
        )

        recent_context = "\n".join(recent_lines) if recent_lines else "最近 7 天暂无历史对话。"
        return initial_messages, recent_context

    @staticmethod
    def build_file_ctx(image_urls: Optional[list[str]], file_urls: Optional[list[str]]) -> str:
        """构建附件上下文文本。"""
        lines: list[str] = []
        if image_urls:
            for url in image_urls:
                resolved = resolve_uploaded_path(url)
                local_path = resolved[1] if resolved else ""
                lines.append(f"- 图片: URL={url}, 本地路径={local_path}" if local_path else f"- 图片: {url}")
        if file_urls:
            for url in file_urls:
                resolved = resolve_uploaded_path(url)
                local_path = resolved[1] if resolved else ""
                filename = url.split("/")[-1]
                lines.append(
                    f"- 文件名: {filename}, URL: {url}, 本地路径={local_path}"
                    if local_path
                    else f"- 文件名: {filename}, URL: {url}"
                )
        if not lines:
            return "用户未上传文件。"
        return "用户上传了以下附件:\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # 后台记忆管道
    # ------------------------------------------------------------------
    async def try_extract_memory(self, user_id: int, session_id: str) -> None:
        """尝试从对话中提取长期记忆事实。当 token 累积超过阈值时触发 FactAgent。"""
        should_trigger = await self.memory.should_trigger_memory_extraction(
            user_id=user_id,
            session_id=session_id,
            module=self.module_name,
            threshold=MEMORY_EXTRACTION_TOKEN_THRESHOLD,
        )
        logger.info(
            "[%s] 记忆提取检查 user=%s session=%s 触发=%s",
            self.module_name, user_id, session_id, should_trigger,
        )
        if not should_trigger:
            return

        success = await self.fact_agent.extract_and_save_fact(user_id=user_id, session_id=session_id)
        if success:
            await self.memory.reset_memory_extraction_counter(
                user_id=user_id, session_id=session_id, module=self.module_name,
            )
            logger.debug("[%s] 记忆提取成功 user=%s session=%s", self.module_name, user_id, session_id)
        else:
            logger.warning("[%s] 记忆提取无更新 user=%s session=%s", self.module_name, user_id, session_id)

    async def try_update_profile(self, user_id: int, session_id: str) -> None:
        """尝试更新用户学习画像。每隔 N 轮 assistant 回复触发一次画像构建。"""
        recent_msgs = await self.memory.get_recent_messages(
            user_id=user_id,
            session_id=session_id,
            module=self.module_name,
            limit=80,
        )
        assistant_turns = sum(1 for m in recent_msgs if getattr(m, "role", "") == "assistant")
        if assistant_turns == 0 or assistant_turns % PROFILE_GATE_EVERY_N_ASSISTANT_TURNS != 0:
            logger.debug(
                "[%s] 画像更新跳过 user=%s session=%s 原因=轮次未到 turns=%s",
                self.module_name, user_id, session_id, assistant_turns,
            )
            return

        dialogue_msgs = [
            m for m in recent_msgs
            if getattr(m, "role", "") in {"user", "assistant"}
            and getattr(m, "content", "").strip()
        ]
        if not dialogue_msgs:
            logger.debug(
                "[%s] 画像更新跳过 user=%s session=%s 原因=无对话",
                self.module_name, user_id, session_id,
            )
            return

        success, updated = await self.profile_agent.build_profile(user_id=user_id, session_id=session_id)
        if success:
            await self.memory.reset_profile_update_counter(
                user_id=user_id, session_id=session_id, module=self.module_name,
            )
            logger.debug(
                "[%s] 画像流程完成 user=%s session=%s updated=%s",
                self.module_name, user_id, session_id, updated,
            )
        else:
            logger.warning(
                "[%s] 画像更新失败 user=%s session=%s",
                self.module_name, user_id, session_id,
            )

    async def try_compress_memory(self, user_id: int, session_id: str) -> None:
        """尝试压缩短期记忆。当 token 累积超过阈值时，将旧消息压缩为摘要存入长期记忆。"""
        await self.memory.summarize_and_compress(
            user_id=user_id,
            session_id=session_id,
            module=self.module_name,
            threshold=MEMORY_COMPRESSION_TOKEN_THRESHOLD,
        )
        logger.debug("[%s] 记忆压缩 user=%s session=%s", self.module_name, user_id, session_id)

    async def post_chat_pipeline(
        self, user_id: int, session_id: str, user_message: str, assistant_reply: str,
    ) -> None:
        """对话完成后的后台处理管道：依次执行记忆提取 → 画像更新 → 记忆压缩。"""
        logger.debug("[%s] 后台流程开始 user=%s session=%s", self.module_name, user_id, session_id)
        try:
            await self.memory.accumulate_session_tokens(
                user_id=user_id,
                session_id=session_id,
                module=self.module_name,
                content=f"{user_message}\n{assistant_reply}",
            )
            await self.try_extract_memory(user_id, session_id)
            await self.try_update_profile(user_id, session_id)
            await self.try_compress_memory(user_id, session_id)
            logger.debug("[%s] 后台流程完成 user=%s session=%s", self.module_name, user_id, session_id)
        except Exception:
            logger.exception("[%s] 后台流程失败 user=%s session=%s", self.module_name, user_id, session_id)

    # ------------------------------------------------------------------
    # 工具记录持久化
    # ------------------------------------------------------------------
    async def persist_tool_messages(
        self, *, user_id: int, session_id: str, tool_call_records: list[ToolCallDetail],
    ) -> None:
        """将工具调用记录保存到数据库，用于历史查看和审计。"""
        if not tool_call_records:
            return
        for record in tool_call_records:
            try:
                tool_name = str(record.get("tool", "unknown"))
                status = str(record.get("status", "success"))
                args = record.get("args", {})
                result = str(record.get("result", ""))
                content = (
                    f"工具调用: {tool_name}\n"
                    f"状态: {status}\n"
                    f"参数: {args}\n"
                    f"结果: {result[:2000]}"
                )
                payload = json.dumps([record], ensure_ascii=False)
                await self.memory.save_message(
                    user_id=user_id,
                    session_id=session_id,
                    module=self.module_name,
                    role="tool",
                    content=content,
                    tool_calls=payload,
                )
                logger.debug(
                    "[%s] 工具记录 user=%s session=%s tool=%s 状态=%s",
                    self.module_name, user_id, session_id, tool_name, status,
                )
            except Exception:
                logger.exception(
                    "[%s] persistence.tool_record.failed user=%s session=%s record=%s",
                    self.module_name, user_id, session_id, truncate(record, 300),
                )


def _build_fact_agent():
    from app.profile import build_fact_agent
    return build_fact_agent()


def _build_profile_agent():
    from app.profile import build_profile_agent
    return build_profile_agent()
