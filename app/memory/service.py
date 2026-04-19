"""
MemoryService — 兼容外观层。

原 MemoryService 已拆分为独立服务：
  - app.memory.session         → 会话管理 + token 累计
  - app.memory.short_term      → 短期记忆 (ChatMessage CRUD)
  - app.memory.long_term       → 长期记忆 (UserMemory 读写/去重)
  - app.memory.compression     → 短期→长期压缩
  - app.memory.helpers         → normalize_text 等共享工具

此类保持向后兼容，所有方法委托给对应服务。
新代码应直接导入对应服务。
"""

from __future__ import annotations

from typing import List, Optional, Iterable

from app.infra.logging import get_logger
from app.infra.models import ChatMessage, ChatSession
from app.infra.models import UserMemory

from app.memory.session import session_service
from app.memory.short_term import short_term_service
from app.memory.long_term import long_term_service
from app.memory.compression import compression_service
from app.memory.helpers import normalize_text, estimate_token_count

logger = get_logger(__name__)

SHORT_TERM_MESSAGE_EXPIRE_DAYS = 7  # 短期消息默认保留天数
MEMORY_COMPRESSION_TOKEN_THRESHOLD = 150  # 触发短期→长期记忆压缩的 token 阈值
MEMORY_EXTRACTION_TOKEN_THRESHOLD = 80  # 触发 FactAgent 长期记忆提取的 token 阈值
PROFILE_UPDATE_TOKEN_THRESHOLD = 120  # 触发 ProfileAgent 画像更新的 token 阈值


class MemoryService:
    """
    兼容外观：委托给拆分后的服务。
    新代码请直接使用对应服务，不再经过此类。
    """

    def __init__(self):
        logger.debug("[MemoryService] 初始化兼容外观层")

    # -- helpers（委托 helpers 模块） --
    @staticmethod
    def _normalize_text(content: str) -> str:
        return normalize_text(content)

    def estimate_token_count(self, text: str) -> int:
        return estimate_token_count(text)

    # -- 会话管理 (委托 session_service) --
    async def create_chat_session(self, user_id: int, module: str, title: str = "新对话") -> ChatSession:
        logger.debug("[MemoryService] 委托 create_chat_session: user_id=%d, module=%s", user_id, module)
        return await session_service.create_chat_session(user_id, module, title)

    async def get_chat_session(self, session_id: str) -> Optional[ChatSession]:
        return await session_service.get_chat_session(session_id)

    async def get_user_chat_sessions(self, user_id: int, module: Optional[str] = None, limit: int = 20) -> List[ChatSession]:
        return await session_service.get_user_chat_sessions(user_id, module, limit)

    async def archive_chat_session(self, session_id: str, user_id: int) -> bool:
        return await session_service.archive_chat_session(session_id, user_id)

    # -- 短期记忆 (委托 short_term_service) --
    async def save_message(
        self, user_id: int, session_id: str, module: str, role: str, content: str,
        attachments: str | None = None, tool_calls: str | None = None,
        resource_cards: str | None = None,
    ) -> int:
        return await short_term_service.save_message(
            user_id, session_id, module, role, content, attachments, tool_calls, resource_cards,
        )

    async def get_recent_messages(
        self, user_id: int, session_id: str, module: str, limit: int | None = None,
        days: int = SHORT_TERM_MESSAGE_EXPIRE_DAYS, only_unexpired: bool = True,
    ) -> list[ChatMessage]:
        return await short_term_service.get_recent_messages(
            user_id, session_id, module, limit, days, only_unexpired,
        )

    async def get_message_count(self, user_id: int, session_id: str, module: str) -> int:
        return await short_term_service.get_message_count(user_id, session_id, module)

    async def delete_old_messages(self, user_id: int, session_id: str, module: str, keep_recent: int = 10) -> int:
        return await short_term_service.delete_old_messages(user_id, session_id, module, keep_recent)

    async def cleanup_expired_short_term_messages(
        self, user_id: int, session_id: str, module: str, days: int = SHORT_TERM_MESSAGE_EXPIRE_DAYS,
    ) -> int:
        return await short_term_service.cleanup_expired_short_term_messages(user_id, session_id, module, days)

    async def should_summarize(
        self,
        user_id: int,
        session_id: str,
        module: str,
        threshold: int = MEMORY_COMPRESSION_TOKEN_THRESHOLD,
    ) -> bool:
        return await short_term_service.should_summarize(user_id, session_id, module, threshold)

    # -- 长期记忆 (委托 long_term_service) --
    async def get_long_term_memories(
        self, user_id: int, module: str | None = None, limit: int = 10, only_unexpired: bool = True,
    ) -> list[UserMemory]:
        return await long_term_service.get_long_term_memories(user_id, module, limit, only_unexpired)

    async def save_user_fact(
        self, user_id: int, content: str, memory_type: str,
        session_id: Optional[str] = None, expires_at=None,
    ) -> UserMemory:
        return await long_term_service.save_user_fact(user_id, content, memory_type, session_id, expires_at)

    async def get_user_facts(self, user_id: int, limit: int = 50) -> List[UserMemory]:
        return await long_term_service.get_user_facts(user_id, limit)

    async def get_user_context_memories(
        self, user_id: int, memory_types: Iterable[str] | None = None,
        per_type_limits: dict[str, int] | None = None, only_unexpired: bool = True,
    ) -> dict[str, list[UserMemory]]:
        return await long_term_service.get_user_context_memories(
            user_id, memory_types, per_type_limits, only_unexpired,
        )

    async def save_long_term_memory(
        self, user_id: int, session_id: str, content: str, memory_type: str,
        dimension: str | None = None, importance: float = 0.5,
        source: str = "conversation", source_message_count: int = 0,
    ) -> UserMemory:
        return await long_term_service.save_long_term_memory(
            user_id, session_id, content, memory_type, dimension, importance, source, source_message_count,
        )

    # -- 画像服务 (延迟导入 profile_service，避免循环依赖) --
    async def get_user_profile(self, user_id: int):
        from app.profile.service import profile_service
        logger.debug("[MemoryService] 委托 get_user_profile: user_id=%d", user_id)
        return await profile_service.get_user_profile(user_id)

    async def update_user_profile(
        self,
        user_id: int,
        features: dict,
        change_reason: str = "系统自动更新",
        source_memory_ids: list[int] | None = None,
    ):
        from app.profile.service import profile_service
        logger.debug("[MemoryService] 委托 update_user_profile: user_id=%d, reason=%s", user_id, change_reason)
        return await profile_service.update_user_profile(
            user_id=user_id,
            features=features,
            change_reason=change_reason,
            source_memory_ids=source_memory_ids,
        )

    # -- 压缩 (委托 compression_service) --
    async def summarize_and_compress(
        self,
        user_id: int,
        session_id: str,
        module: str,
        threshold: int = MEMORY_COMPRESSION_TOKEN_THRESHOLD,
        keep_recent: int = 10,
    ) -> None:
        await compression_service.summarize_and_compress(user_id, session_id, module, threshold, keep_recent)

    # -- token 计数 (委托 session_service) --
    async def accumulate_session_tokens(
        self, user_id: int, session_id: str, module: str, content: str,
    ) -> tuple[int, int]:
        return await session_service.accumulate_session_tokens(user_id, session_id, module, content)

    async def get_session_token_counters(self, user_id: int, session_id: str, module: str) -> tuple[int, int]:
        return await session_service.get_session_token_counters(user_id, session_id, module)

    async def should_trigger_memory_extraction(
        self, user_id: int, session_id: str, module: str, threshold: int = MEMORY_EXTRACTION_TOKEN_THRESHOLD,
    ) -> bool:
        return await session_service.should_trigger_memory_extraction(user_id, session_id, module, threshold)

    async def should_trigger_profile_update_by_tokens(
        self, user_id: int, session_id: str, module: str, threshold: int = PROFILE_UPDATE_TOKEN_THRESHOLD,
    ) -> bool:
        return await session_service.should_trigger_profile_update_by_tokens(user_id, session_id, module, threshold)

    async def reset_memory_extraction_counter(self, user_id: int, session_id: str, module: str) -> None:
        await session_service.reset_memory_extraction_counter(user_id, session_id, module)

    async def reset_profile_update_counter(self, user_id: int, session_id: str, module: str) -> None:
        await session_service.reset_profile_update_counter(user_id, session_id, module)


memory_service = MemoryService()  # 模块级单例（兼容旧代码）
