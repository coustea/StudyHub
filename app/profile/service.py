"""Profile service — 画像服务 + 学习者状态 + 画像运行时。"""

from __future__ import annotations

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import engine
from app.infra.logging import get_logger
from app.infra.models import UserProfile, UserProfileHistory

logger = get_logger(__name__)


class ProfileService:
    """用户画像读写与版本管理。"""

    def __init__(self) -> None:
        self.engine = engine

    async def get_user_profile(self, user_id: int) -> UserProfile | None:
        async with AsyncSession(self.engine) as session:
            return await session.get(UserProfile, user_id)

    async def update_user_profile(
        self,
        user_id: int,
        features: dict,
        change_reason: str = "系统自动更新",
        source_memory_ids: list[int] | None = None,
    ) -> UserProfile:
        async with AsyncSession(self.engine) as session:
            import json
            async with session.begin():
                profile = await session.get(UserProfile, user_id)
                if not profile:
                    profile = UserProfile(user_id=user_id)

                for field, value in features.items():
                    if hasattr(profile, field):
                        setattr(profile, field, value)

                session.add(profile)
                await session.flush()

                version_stmt = select(func.max(UserProfileHistory.version)).where(
                    UserProfileHistory.user_id == user_id
                )
                latest_version = (await session.exec(version_stmt)).one()
                next_version = 0 if latest_version is None else int(latest_version) + 1
                history = UserProfileHistory(
                    user_id=user_id,
                    version=next_version,
                    knowledge_level=profile.knowledge_level,
                    knowledge_level_score=profile.knowledge_level_score,
                    learning_goal=profile.learning_goal,
                    learning_goal_score=profile.learning_goal_score,
                    learning_history=profile.learning_history,
                    learning_history_score=profile.learning_history_score,
                    cognitive_style=profile.cognitive_style,
                    cognitive_style_score=profile.cognitive_style_score,
                    error_pattern=profile.error_pattern,
                    error_pattern_score=profile.error_pattern_score,
                    learning_pace=profile.learning_pace,
                    learning_pace_score=profile.learning_pace_score,
                    interest_preference=profile.interest_preference,
                    interest_preference_score=profile.interest_preference_score,
                    cognitive_level=profile.cognitive_level,
                    cognitive_level_score=profile.cognitive_level_score,
                    profile_summary=profile.profile_summary,
                    change_reason=change_reason,
                    source_memory_ids=json.dumps(source_memory_ids) if source_memory_ids else None,
                )
                session.add(history)

            await session.refresh(profile)

            return profile

    async def get_profile_history(self, user_id: int, limit: int = 20) -> list[UserProfileHistory]:
        async with AsyncSession(self.engine) as session:
            stmt = (
                select(UserProfileHistory)
                .where(UserProfileHistory.user_id == user_id)
                .order_by(UserProfileHistory.created_at.desc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())


class LearnerProfileRuntime:
    """画像运行时：触发画像构建和事实提取。"""

    async def build_profile(self, user_id: int, session_id: str | None = None) -> bool:
        from app.shared.request_context import set_user_id
        set_user_id(user_id)
        agent = _build_profile_agent()
        success, _ = await agent.build_profile(user_id=user_id, session_id=session_id)
        return success

    async def extract_facts(self, user_id: int, session_id: str) -> bool:
        agent = _build_fact_agent()
        return await agent.extract_and_save_fact(user_id=user_id, session_id=session_id)


class ProfileUseCases:
    """画像相关用例。"""

    def __init__(self, profile_svc: ProfileService) -> None:
        self.profile_svc = profile_svc

    async def get_profile(self, user_id: int):
        return await self.profile_svc.get_user_profile(user_id)

    async def get_profile_history(self, user_id: int, limit: int = 20):
        return await self.profile_svc.get_profile_history(user_id, limit)


def _build_profile_agent():
    from app.profile.profile_agent import ProfileBuilderAgent
    return ProfileBuilderAgent()


def _build_fact_agent():
    from app.profile.fact_agent import MemoryExtractionAgent
    return MemoryExtractionAgent()


# 模块级单例
profile_service = ProfileService()
learner_profile_runtime = LearnerProfileRuntime()
profile_usecases = ProfileUseCases(profile_service)
