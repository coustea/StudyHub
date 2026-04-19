"""
长期记忆服务。

从 MemoryService 拆分：UserMemory 读写、去重/合并、按类型查询。
职责：管理用户长期记忆的持久化存储，支持精确去重、语义近似合并和按类型限量查询。
"""

from collections import defaultdict
from typing import Iterable

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import engine
from app.infra.logging import get_logger
from app.infra.models import UserMemory
from app.memory.helpers import normalize_text, now
from app.memory.memory_types import (
    FACT_AGENT_MEMORY_TYPES,
    MEMORY_TYPE_BACKGROUND,
    MEMORY_TYPE_FACT,
    MEMORY_TYPE_GOAL,
    MEMORY_TYPE_PREFERENCE,
    MEMORY_TYPE_WEAKNESS,
)

logger = get_logger(__name__)

# 各类型记忆的默认数量上限，查询时按此限制返回条数
DEFAULT_MEMORY_TYPE_LIMITS: dict[str, int] = {
    MEMORY_TYPE_PREFERENCE: 3,   # 用户偏好（如"喜欢图解说明"）
    MEMORY_TYPE_GOAL: 2,         # 学习目标（如"准备数据结构考试"）
    MEMORY_TYPE_WEAKNESS: 3,     # 薄弱点（如"递归理解困难"）
    MEMORY_TYPE_FACT: 3,         # 事实信息（如"正在学 Python"）
    MEMORY_TYPE_BACKGROUND: 2,   # 背景信息（如"计算机专业大二"）
}


class LongTermMemoryService:
    """长期记忆（UserMemory）的读写、去重/合并、按类型查询。"""

    def __init__(self) -> None:
        self.engine = engine  # 复用全局数据库引擎

    @staticmethod
    def _should_merge_fact(memory_type: str, new_text: str, existing_text: str) -> bool:
        """同类长期记忆的轻量合并策略（基于子串包含关系），避免重复堆叠。
        仅对 goal/preference/weakness 三类进行合并判断，fact 和 background 不合并。
        合并条件：归一化后的新文本是旧文本的子串，或反之。"""
        if memory_type not in {MEMORY_TYPE_GOAL, MEMORY_TYPE_PREFERENCE, MEMORY_TYPE_WEAKNESS}:
            return False
        if not existing_text:
            return False
        normalized_new = normalize_text(new_text)
        normalized_existing = normalize_text(existing_text)
        if not normalized_new or not normalized_existing:
            return False
        # 子串包含关系判断：如果新内容已被旧内容包含，或旧内容被新内容包含，则视为重复
        return normalized_new in normalized_existing or normalized_existing in normalized_new

    async def save_user_fact(
        self,
        user_id: int,
        content: str,
        memory_type: str,
        session_id: str | None = None,
        expires_at=None,
    ) -> UserMemory:
        """保存单条用户事实/偏好到 UserMemory 表（带去重/合并/计数）。
        流程：
        1. 校验和标准化 memory_type，未知类型回退为 "fact"
        2. 精确去重：如果已有归一化内容完全相同的记录，则增加 evidence_count 并返回
        3. 近似合并：如果同类记忆中存在语义近似的记录，保留较长内容并增加 evidence_count
        4. 新建记录：如果以上都不匹配，创建新的 UserMemory 记录
        """
        normalized_type = (memory_type or MEMORY_TYPE_FACT).strip().lower()
        if normalized_type not in FACT_AGENT_MEMORY_TYPES:
            logger.warning("[LongTermMemory] 未知 memory_type=%s, 已回退为 fact", memory_type)
            normalized_type = MEMORY_TYPE_FACT

        cleaned_content = (content or "").strip()
        normalized_content = normalize_text(cleaned_content)
        if not normalized_content:
            raise ValueError("记忆内容不能为空")

        async with AsyncSession(self.engine) as session:
            _now = now()

            # 第一步：精确重复去重 — 查找同用户、同类型、未过期的已有记忆
            exact_stmt = (
                select(UserMemory)
                .where(
                    UserMemory.user_id == user_id,
                    UserMemory.source == "fact_agent",  # 只比较 FactAgent 产出的记忆
                    UserMemory.memory_type == normalized_type,
                    or_(UserMemory.expires_at == None, UserMemory.expires_at > _now),  # noqa: E711 — 未过期
                )
                .order_by(UserMemory.created_at.desc())  # 优先匹配最新的记录
            )
            candidates = list((await session.exec(exact_stmt)).all())
            logger.debug("[LongTermMemory] 去重候选数: user=%d, type=%s, candidates=%d",
                         user_id, normalized_type, len(candidates))

            # 精确匹配：归一化后内容完全相同则视为重复
            for duplicate in candidates:
                if normalize_text(duplicate.content) == normalized_content:
                    duplicate.evidence_count = max(1, duplicate.evidence_count) + 1  # 增加出现次数
                    duplicate.last_seen_at = _now  # 更新最后出现时间
                    duplicate.session_id = session_id or duplicate.session_id
                    if expires_at:
                        duplicate.expires_at = expires_at
                    session.add(duplicate)
                    await session.commit()
                    await session.refresh(duplicate)
                    logger.info("[LongTermMemory] 精确去重命中: user=%d, type=%s, "
                                "evidence_count=%d, memory_id=%d",
                                user_id, normalized_type, duplicate.evidence_count, duplicate.id)
                    return duplicate

            # 第二步：同类型语义近似合并（基于子串包含规则）
            for candidate in candidates:
                if self._should_merge_fact(normalized_type, cleaned_content, candidate.content):
                    # 保留较长的内容（信息量更大）
                    merged_content = candidate.content
                    if len(cleaned_content) > len(candidate.content):
                        merged_content = cleaned_content
                    candidate.content = merged_content
                    candidate.evidence_count = max(1, candidate.evidence_count) + 1
                    candidate.last_seen_at = _now
                    candidate.session_id = session_id or candidate.session_id
                    if expires_at:
                        candidate.expires_at = expires_at
                    session.add(candidate)
                    await session.commit()
                    await session.refresh(candidate)
                    logger.info("[LongTermMemory] 近似合并命中: user=%d, type=%s, "
                                "merged_len=%d, evidence_count=%d, memory_id=%d",
                                user_id, normalized_type, len(merged_content),
                                candidate.evidence_count, candidate.id)
                    return candidate

            # 第三步：无重复，创建新记录
            memory = UserMemory(
                user_id=user_id,
                session_id=session_id or "",
                content=cleaned_content,
                memory_type=normalized_type,
                source="fact_agent",
                expires_at=expires_at,
                evidence_count=1,  # 首次出现的证据计数为 1
                last_seen_at=_now,
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            logger.info("[LongTermMemory] 新建记忆: user=%d, type=%s, memory_id=%d, content_len=%d",
                        user_id, normalized_type, memory.id, len(cleaned_content))
            return memory

    async def get_user_facts(self, user_id: int, limit: int = 50) -> list[UserMemory]:
        """兼容旧接口：获取用户长期事实。
        内部调用 get_user_context_memories 并将结果展平为单列表。"""
        memories_by_type = await self.get_user_context_memories(
            user_id=user_id,
            per_type_limits={
                MEMORY_TYPE_FACT: limit,
                MEMORY_TYPE_PREFERENCE: limit,
                MEMORY_TYPE_GOAL: limit,
                MEMORY_TYPE_WEAKNESS: limit,
                MEMORY_TYPE_BACKGROUND: limit,
            },
        )
        flat: list[UserMemory] = []
        for _, items in memories_by_type.items():
            flat.extend(items)
        # 按 last_seen_at 倒序排列（最近出现的优先），回退到 created_at
        flat.sort(key=lambda x: x.last_seen_at or x.created_at, reverse=True)
        logger.debug("[LongTermMemory] 获取用户事实: user=%d, total_types=%d, total_items=%d, limit=%d",
                     user_id, len(memories_by_type), len(flat), limit)
        return flat[:limit]

    async def get_user_context_memories(
        self,
        user_id: int,
        memory_types: Iterable[str] | None = None,
        per_type_limits: dict[str, int] | None = None,
        only_unexpired: bool = True,
        source: str | None = "fact_agent",
    ) -> dict[str, list[UserMemory]]:
        """按类型返回用于上下文注入的长期记忆，自动去重与限量。
        返回格式：{"preference": [...], "goal": [...], ...}
        每个类型内部按 last_seen_at 倒序排列，且经过归一化去重。
        source 参数：按来源过滤记忆，默认 "fact_agent"。传 None 不过滤来源。"""
        target_types = list(memory_types) if memory_types else list(DEFAULT_MEMORY_TYPE_LIMITS.keys())
        limits = dict(DEFAULT_MEMORY_TYPE_LIMITS)  # 复制默认限制
        if per_type_limits:
            limits.update(per_type_limits)  # 允许调用方覆盖特定类型的限制

        async with AsyncSession(self.engine) as session:
            _now = now()
            stmt = select(UserMemory).where(UserMemory.user_id == user_id)
            if source is not None:
                stmt = stmt.where(UserMemory.source == source)
            if target_types:
                stmt = stmt.where(UserMemory.memory_type.in_(target_types))  # 按类型过滤
            if only_unexpired:
                stmt = stmt.where(or_(UserMemory.expires_at == None, UserMemory.expires_at > _now))  # noqa: E711
            stmt = stmt.order_by(UserMemory.last_seen_at.desc(), UserMemory.created_at.desc())
            result = await session.exec(stmt)
            memories = list(result.all())
            logger.debug("[LongTermMemory] 查询上下文记忆: user=%d, types=%s, raw_count=%d",
                         user_id, target_types, len(memories))

        # 内存中去重和限量：同类型内归一化内容相同的只保留一条
        grouped: dict[str, list[UserMemory]] = defaultdict(list)
        seen_by_type: dict[str, set[str]] = defaultdict(set)  # 每个类型已见过的归一化内容
        for item in memories:
            m_type = item.memory_type or MEMORY_TYPE_FACT
            if m_type not in target_types:
                continue
            normalized = normalize_text(item.content)
            if not normalized or normalized in seen_by_type[m_type]:
                continue  # 跳过空内容或重复内容
            limit = max(0, limits.get(m_type, 2))
            if len(grouped[m_type]) >= limit:
                continue  # 该类型已达上限
            seen_by_type[m_type].add(normalized)
            grouped[m_type].append(item)

        result_dict = {m_type: grouped.get(m_type, []) for m_type in target_types}
        total_items = sum(len(v) for v in result_dict.values())
        logger.info("[LongTermMemory] 上下文记忆汇总: user=%d, total_items=%d, "
                     "per_type=%s",
                     user_id, total_items,
                     {k: len(v) for k, v in result_dict.items()})
        return result_dict

    async def get_long_term_memories(
        self,
        user_id: int,
        module: str | None = None,
        limit: int = 10,
        only_unexpired: bool = True,
    ) -> list[UserMemory]:
        """获取用户长期记忆列表（通用查询接口）。
        module 参数用于按来源过滤（如 "conversation"），不传则不过滤。"""
        async with AsyncSession(self.engine) as session:
            stmt = select(UserMemory).where(UserMemory.user_id == user_id)
            if module is not None:
                stmt = stmt.where(UserMemory.source == module)
            if only_unexpired:
                _now = now()
                stmt = stmt.where(or_(UserMemory.expires_at == None, UserMemory.expires_at > _now))  # noqa: E711
            stmt = stmt.order_by(UserMemory.created_at.desc()).limit(limit)
            result = await session.exec(stmt)
            memories = list(result.all())
            logger.debug("[LongTermMemory] 通用查询: user=%d, module=%s, returned=%d",
                         user_id, module, len(memories))
            return memories

    async def save_long_term_memory(
        self,
        user_id: int,
        session_id: str,
        content: str,
        memory_type: str,
        dimension: str | None = None,
        importance: float = 0.5,
        source: str = "conversation",
        source_message_count: int = 0,
    ) -> UserMemory:
        """将 LLM 提炼的长期记忆条目写入 user_memory 表（无去重，直接写入）。
        与 save_user_fact 不同，此方法不做去重/合并，适用于批量写入场景（如压缩服务产出摘要）。"""
        async with AsyncSession(self.engine) as session:
            memory = UserMemory(
                user_id=user_id,
                session_id=session_id,
                content=content,
                memory_type=memory_type,
                dimension=dimension,  # 可选维度标签（如 "knowledge_level"）
                importance=importance,  # 重要性评分 0.0~1.0
                source=source,  # 来源标识："conversation" | "fact_agent" | module名
                source_message_count=source_message_count,  # 来源消息条数
                evidence_count=1,
                last_seen_at=now(),
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            logger.info("[LongTermMemory] 保存长期记忆: user=%d, type=%s, source=%s, "
                        "importance=%.2f, memory_id=%d, content_len=%d",
                        user_id, memory_type, source, importance, memory.id, len(content))
            return memory


long_term_service = LongTermMemoryService()  # 模块级单例
