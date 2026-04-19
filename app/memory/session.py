"""
会话管理服务。

从 MemoryService 拆分：ChatSession CRUD + token 累计。
职责：创建/查询/归档会话，维护会话级 token 计数器（用于判断何时触发记忆提取和画像更新）。
"""

from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import engine
from app.infra.logging import get_logger
from app.infra.models import ChatSession
from app.memory.helpers import now, estimate_token_count

logger = get_logger(__name__)


class SessionService:
    """ChatSession CRUD 及 token 累计管理。"""

    def __init__(self) -> None:
        self.engine = engine  # 复用全局数据库引擎

    async def _get_owned_session(
        self,
        session: AsyncSession,
        user_id: int,
        session_id: str,
        module: str | None = None,
    ) -> ChatSession | None:
        """查询并校验会话归属：确保 session_id 对应的会话属于指定 user_id。
        如果传入 module 则额外过滤模块，防止跨模块访问。"""
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        if module is not None:
            stmt = stmt.where(ChatSession.module == module)
        result = await session.exec(stmt)
        found = result.first()
        if not found:
            logger.debug("[Session] 会话不存在或不属于用户: session_id=%s, user_id=%d", session_id, user_id)
        return found

    async def create_chat_session(
        self, user_id: int, module: str, title: str = "新对话"
    ) -> ChatSession:
        """创建新的聊天会话，返回包含自增 ID 和默认值的 ChatSession 对象。"""
        async with AsyncSession(self.engine) as session:
            chat_session = ChatSession(user_id=user_id, module=module, title=title)
            session.add(chat_session)
            await session.commit()
            await session.refresh(chat_session)  # 刷新以获取数据库生成的 id 和默认字段值
            logger.info("[Session] 创建新会话: session_id=%s, user_id=%d, module=%s, title=%s",
                        chat_session.id, user_id, module, title)
            return chat_session

    async def get_chat_session(self, session_id: str) -> Optional[ChatSession]:
        """根据 session_id 查询单个会话（不校验归属，仅供内部使用）。"""
        async with AsyncSession(self.engine) as session:
            stmt = select(ChatSession).where(ChatSession.id == session_id)
            result = await session.exec(stmt)
            chat_session = result.first()
            if chat_session:
                logger.debug("[Session] 查询到会话: session_id=%s, user_id=%d", session_id, chat_session.user_id)
            else:
                logger.debug("[Session] 会话不存在: session_id=%s", session_id)
            return chat_session

    async def get_user_chat_sessions(
        self,
        user_id: int,
        module: Optional[str] = None,
        limit: int = 20,
    ) -> List[ChatSession]:
        """获取用户的活跃会话列表（已归档的排除），按最近更新时间倒序排列。"""
        async with AsyncSession(self.engine) as session:
            stmt = select(ChatSession).where(
                ChatSession.user_id == user_id,
                ChatSession.is_archived == False,  # noqa: E712 — SQLAlchemy 布尔比较需要 ==
            )
            if module:
                stmt = stmt.where(ChatSession.module == module)
            stmt = stmt.order_by(ChatSession.updated_at.desc()).limit(limit)
            result = await session.exec(stmt)
            sessions = list(result.all())
            logger.debug("[Session] 查询用户会话列表: user_id=%d, module=%s, count=%d",
                         user_id, module, len(sessions))
            return sessions

    async def archive_chat_session(self, session_id: str, user_id: int) -> bool:
        """软删除（归档）会话：将 is_archived 标记为 True，而非物理删除。"""
        async with AsyncSession(self.engine) as session:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
            result = await session.exec(stmt)
            chat_session = result.first()
            if not chat_session:
                logger.warning("[Session] 归档失败，会话不存在或不属于用户: session_id=%s, user_id=%d",
                               session_id, user_id)
                return False
            chat_session.is_archived = True
            session.add(chat_session)
            await session.commit()
            logger.info("[Session] 会话已归档: session_id=%s, user_id=%d", session_id, user_id)
            return True

    async def accumulate_session_tokens(
        self,
        user_id: int,
        session_id: str,
        module: str,
        content: str,
    ) -> tuple[int, int]:
        """累加会话 token 计数（长期记忆提取计数 + 画像更新计数）。
        两个计数器独立累加但同步重置时机不同：
        - memory_token_count: 达到阈值后触发 FactAgent 提取长期记忆，然后重置
        - profile_token_count: 达到阈值后触发 ProfileAgent 更新画像，然后重置
        返回 (memory_token_count, profile_token_count)。"""
        token_delta = estimate_token_count(content)  # 估算本轮内容的 token 数
        async with AsyncSession(self.engine) as session:
            chat_session = await self._get_owned_session(session, user_id, session_id, module)
            if not chat_session:
                # 会话不存在时自动创建（兜底逻辑，正常流程应先 create_chat_session）
                chat_session = ChatSession(id=session_id, user_id=user_id, module=module, title="新对话")
            memory_token_count = max(0, chat_session.memory_token_count + token_delta)
            profile_token_count = max(0, chat_session.profile_token_count + token_delta)
            chat_session.memory_token_count = memory_token_count
            chat_session.profile_token_count = profile_token_count
            chat_session.updated_at = now()
            session.add(chat_session)
            await session.commit()
            logger.info("[Session] token 累加完成: session_id=%s, user_id=%d, delta=%d, "
                        "memory_tokens=%d, profile_tokens=%d",
                        session_id, user_id, token_delta, memory_token_count, profile_token_count)
            return memory_token_count, profile_token_count

    async def get_session_token_counters(
        self, user_id: int, session_id: str, module: str
    ) -> tuple[int, int]:
        """读取当前会话的两个 token 计数器值，会话不存在则返回 (0, 0)。"""
        async with AsyncSession(self.engine) as session:
            chat_session = await self._get_owned_session(session, user_id, session_id, module)
            if not chat_session:
                logger.debug("[Session] 读取 token 计数器: 会话不存在, 返回 (0,0), session_id=%s", session_id)
                return 0, 0
            logger.debug("[Session] 读取 token 计数器: session_id=%s, memory=%d, profile=%d",
                         session_id, chat_session.memory_token_count, chat_session.profile_token_count)
            return chat_session.memory_token_count, chat_session.profile_token_count

    async def should_trigger_memory_extraction(
        self,
        user_id: int,
        session_id: str,
        module: str,
        threshold: int = 80,
    ) -> bool:
        """判断是否应触发长期记忆提取：当 memory_token_count 累计达到阈值时返回 True。"""
        memory_tokens, _ = await self.get_session_token_counters(user_id, session_id, module)
        triggered = memory_tokens >= threshold
        if triggered:
            logger.info("[Session] 触发记忆提取: session_id=%s, user_id=%d, "
                        "memory_tokens=%d >= threshold=%d",
                        session_id, user_id, memory_tokens, threshold)
        else:
            logger.debug("[Session] 记忆提取未达阈值: session_id=%s, memory_tokens=%d/%d",
                         session_id, memory_tokens, threshold)
        return triggered

    async def should_trigger_profile_update_by_tokens(
        self,
        user_id: int,
        session_id: str,
        module: str,
        threshold: int = 120,
    ) -> bool:
        """判断是否应触发画像更新：当 profile_token_count 累计达到阈值时返回 True。"""
        _, profile_tokens = await self.get_session_token_counters(user_id, session_id, module)
        triggered = profile_tokens >= threshold
        if triggered:
            logger.info("[Session] 触发画像更新: session_id=%s, user_id=%d, "
                        "profile_tokens=%d >= threshold=%d",
                        session_id, user_id, profile_tokens, threshold)
        else:
            logger.debug("[Session] 画像更新未达阈值: session_id=%s, profile_tokens=%d/%d",
                         session_id, profile_tokens, threshold)
        return triggered

    async def reset_memory_extraction_counter(
        self, user_id: int, session_id: str, module: str
    ) -> None:
        """将 memory_token_count 重置为 0（在 FactAgent 完成记忆提取后调用）。"""
        async with AsyncSession(self.engine) as session:
            chat_session = await self._get_owned_session(session, user_id, session_id, module)
            if not chat_session:
                logger.warning("[Session] 重置记忆提取计数器失败: 会话不存在, session_id=%s", session_id)
                return
            chat_session.memory_token_count = 0
            session.add(chat_session)
            await session.commit()
            logger.info("[Session] 记忆提取计数器已重置: session_id=%s, user_id=%d", session_id, user_id)

    async def reset_profile_update_counter(
        self, user_id: int, session_id: str, module: str
    ) -> None:
        """将 profile_token_count 重置为 0（在 ProfileAgent 完成画像更新后调用）。"""
        async with AsyncSession(self.engine) as session:
            chat_session = await self._get_owned_session(session, user_id, session_id, module)
            if not chat_session:
                logger.warning("[Session] 重置画像更新计数器失败: 会话不存在, session_id=%s", session_id)
                return
            chat_session.profile_token_count = 0
            session.add(chat_session)
            await session.commit()
            logger.info("[Session] 画像更新计数器已重置: session_id=%s, user_id=%d", session_id, user_id)


session_service = SessionService()  # 模块级单例