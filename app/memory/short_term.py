"""
短期记忆服务。

从 MemoryService 拆分：ChatMessage CRUD（保存、查询、计数、清理）。
职责：管理聊天消息的持久化存储，支持按会话查询、过期清理和总结判断。
"""

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import engine
from app.infra.logging import get_logger
from app.infra.models import ChatMessage, ChatSession
from app.memory.helpers import now, message_expire_cutoff, estimate_token_count

logger = get_logger(__name__)

SHORT_TERM_MESSAGE_EXPIRE_DAYS = 7  # 短期消息默认保留天数


class ShortTermMemoryService:
    """短期记忆（ChatMessage）的读写与清理。"""

    def __init__(self) -> None:
        self.engine = engine  # 复用全局数据库引擎

    async def save_message(
        self,
        user_id: int,
        session_id: str,
        module: str,
        role: str,
        content: str,
        attachments: str | None = None,
        tool_calls: str | None = None,
        resource_cards: str | None = None,
    ) -> int:
        """存入一条消息，同时确保对应的 ChatSession 存在。
        如果会话已存在则校验归属并更新时间戳；如果不存在则自动创建。
        返回当前会话的消息总数。"""
        async with AsyncSession(self.engine) as session:
            # 查找会话以确保存在且归属正确
            session_stmt = select(ChatSession).where(ChatSession.id == session_id)
            result = await session.exec(session_stmt)
            chat_session = result.first()
            if chat_session:
                # 校验会话归属：防止用户向非自己的会话写入消息
                if chat_session.user_id != user_id or chat_session.module != module:
                    logger.error("[ShortTermMemory] 会话归属校验失败: session_id=%s, "
                                 "expected_user=%d/module=%s, actual_user=%d/module=%s",
                                 session_id, user_id, module, chat_session.user_id, chat_session.module)
                    raise PermissionError("会话不属于当前用户或模块，禁止写入")
                chat_session.updated_at = now()  # 更新会话的最后活动时间
            else:
                # 会话不存在则自动创建（以消息前 20 字符作为标题）
                chat_session = ChatSession(id=session_id, user_id=user_id, module=module, title=content[:20])
                logger.info("[ShortTermMemory] 自动创建会话: session_id=%s, user_id=%d", session_id, user_id)
            session.add(chat_session)

            # 创建消息记录
            msg = ChatMessage(
                user_id=user_id,
                session_id=session_id,
                module=module,
                role=role,  # "user" | "assistant" | "system" | "tool"
                content=content,
                attachments=attachments,  # 附件信息（JSON 字符串）
                tool_calls=tool_calls,  # 工具调用记录（JSON 字符串）
            )
            session.add(msg)
            await session.commit()

        # 查询当前会话的消息总数并返回
        count = await self.get_message_count(user_id, session_id, module)
        logger.debug("[ShortTermMemory] 消息已保存: session_id=%s, role=%s, msg_len=%d, total_count=%d",
                     session_id, role, len(content), count)
        return count

    async def get_recent_messages(
        self,
        user_id: int,
        session_id: str,
        module: str,
        limit: int | None = None,
        days: int = SHORT_TERM_MESSAGE_EXPIRE_DAYS,
        only_unexpired: bool = True,
    ) -> list[ChatMessage]:
        """获取指定会话的最近 N 条消息。
        使用 offset+limit 而非倒序截取，确保返回的是"最早的(total-limit)条到最新条"。
        only_unexpired=True 时过滤掉超过 days 天的过期消息。"""
        async with AsyncSession(self.engine) as session:
            # 构建基础过滤条件：用户 + 会话 + 模块
            filters = [
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
                ChatMessage.module == module,
            ]
            if only_unexpired:
                filters.append(ChatMessage.created_at >= message_expire_cutoff(days))

            # 先查询总数，用于计算 offset
            count_stmt = select(func.count()).where(*filters)
            count_result = await session.exec(count_stmt)
            total = count_result.one()

            # 按时间升序排列，如果总数超过 limit 则跳过前面的旧消息
            stmt = select(ChatMessage).where(*filters).order_by(ChatMessage.created_at.asc())

            if limit is not None and limit > 0 and total > limit:
                stmt = stmt.offset(total - limit)  # 跳过最早的 (total-limit) 条，只取最近 limit 条

            result = await session.exec(stmt)
            messages = list(result.all())
            logger.debug("[ShortTermMemory] 查询最近消息: session_id=%s, total=%d, limit=%s, returned=%d, "
                         "only_unexpired=%s, days=%d",
                         session_id, total, limit, len(messages), only_unexpired, days)
            return messages

    async def get_message_count(
        self, user_id: int, session_id: str, module: str
    ) -> int:
        """统计指定会话的消息总数（不过滤过期）。"""
        async with AsyncSession(self.engine) as session:
            stmt = select(func.count()).where(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
                ChatMessage.module == module,
            )
            result = await session.exec(stmt)
            count = result.one()
            logger.debug("[ShortTermMemory] 消息计数: session_id=%s, count=%d", session_id, count)
            return count

    async def get_message_token_count(
        self,
        user_id: int,
        session_id: str,
        module: str,
        days: int = SHORT_TERM_MESSAGE_EXPIRE_DAYS,
        only_unexpired: bool = True,
    ) -> int:
        """统计指定会话短期消息的估算 token 总量。"""
        messages = await self.get_recent_messages(
            user_id=user_id,
            session_id=session_id,
            module=module,
            limit=None,
            days=days,
            only_unexpired=only_unexpired,
        )
        total_tokens = sum(estimate_token_count(getattr(msg, "content", "")) for msg in messages)
        logger.debug("[ShortTermMemory] 消息 token 计数: session_id=%s, total_tokens=%d, message_count=%d",
                     session_id, total_tokens, len(messages))
        return total_tokens

    async def delete_old_messages(
        self,
        user_id: int,
        session_id: str,
        module: str,
        keep_recent: int = 10,
    ) -> int:
        """删除已被总结过的旧短期消息，仅保留最近 keep_recent 条。
        策略：找到倒数第 keep_recent 条消息的 id，删除所有 id 更小的消息。
        这些旧消息已被压缩为长期记忆，不再需要保留在短期存储中。"""
        async with AsyncSession(self.engine) as session:
            # 先统计总数，判断是否需要清理
            count_stmt = select(func.count()).where(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
                ChatMessage.module == module,
            )
            count_result = await session.exec(count_stmt)
            total = count_result.one()

            if total <= keep_recent:
                logger.debug("[ShortTermMemory] 消息数未超过保留阈值: session_id=%s, total=%d <= keep=%d",
                             session_id, total, keep_recent)
                return 0

            # 找到保留边界：倒数第 keep_recent 条消息的 id
            # 使用 DESC + offset + limit(1) 定位到分界点
            keep_stmt = (
                select(ChatMessage.id)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.session_id == session_id,
                    ChatMessage.module == module,
                )
                .order_by(ChatMessage.created_at.desc())
                .offset(keep_recent - 1)  # 跳过最新的 (keep_recent-1) 条
                .limit(1)  # 取到第 keep_recent 条（即保留边界）
            )
            result = await session.exec(keep_stmt)
            cutoff_id = result.first()

            if cutoff_id is None:
                logger.debug("[ShortTermMemory] 未找到保留边界: session_id=%s", session_id)
                return 0

            # 查询所有 id < cutoff_id 的旧消息并逐条删除
            old_msgs_stmt = select(ChatMessage).where(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
                ChatMessage.module == module,
                ChatMessage.id < cutoff_id,  # 删除分界点之前的所有消息
            )
            old_msgs_result = await session.exec(old_msgs_stmt)
            old_msgs = old_msgs_result.all()

            deleted = len(old_msgs)
            for msg in old_msgs:
                await session.delete(msg)
            await session.commit()
            logger.info("[ShortTermMemory] 清理旧消息: user=%d, session_id=%s, deleted=%d, kept=%d",
                        user_id, session_id, deleted, keep_recent)
            return deleted

    async def cleanup_expired_short_term_messages(
        self,
        user_id: int,
        session_id: str,
        module: str,
        days: int = SHORT_TERM_MESSAGE_EXPIRE_DAYS,
    ) -> int:
        """物理删除超出有效期的短期消息（基于 created_at 字段）。
        与 delete_old_messages 不同，此方法按时间过期而非按数量保留。"""
        cutoff = message_expire_cutoff(days)
        async with AsyncSession(self.engine) as session:
            stmt = select(ChatMessage).where(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
                ChatMessage.module == module,
                ChatMessage.created_at < cutoff,  # 早于截止时间的消息视为过期
            )
            result = await session.exec(stmt)
            expired_msgs = list(result.all())
            for msg in expired_msgs:
                await session.delete(msg)
            if expired_msgs:
                await session.commit()
            logger.info("[ShortTermMemory] 过期消息清理: user=%d, session_id=%s, "
                        "expired_count=%d, cutoff=%s",
                        user_id, session_id, len(expired_msgs), cutoff.isoformat())
            return len(expired_msgs)

    async def should_summarize(
        self, user_id: int, session_id: str, module: str, threshold: int = 800
    ) -> bool:
        """判断短期记忆是否达到总结阈值（短期消息 token 总量 >= threshold）。
        用于触发短期→长期记忆的压缩流程。"""
        token_count = await self.get_message_token_count(user_id, session_id, module)
        should = token_count >= threshold
        logger.debug("[ShortTermMemory] 总结判断: session_id=%s, token_count=%d, threshold=%d, should=%s",
                     session_id, token_count, threshold, should)
        return should


short_term_service = ShortTermMemoryService()  # 模块级单例
