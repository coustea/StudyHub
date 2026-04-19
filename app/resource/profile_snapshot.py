from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import engine
from app.infra.logging import get_logger
from app.infra.models import User
from app.memory.service import memory_service
from app.resource.schemas import LearnerProfileSnapshot, PersonalizedTaskContext

logger = get_logger(__name__)


class ProfileSnapshotLoader:
    async def load(self, user_id: int) -> LearnerProfileSnapshot:
        logger.info("[ProfileSnapshot] 开始组装画像快照: user_id=%s", user_id)
        user_data = await self._load_user(user_id)
        profile_data = await self._load_profile(user_id)
        snapshot = LearnerProfileSnapshot.from_sources(user_data=user_data, profile_data=profile_data)
        logger.info(
            "[ProfileSnapshot] 画像快照组装完成: user_id=%s major=%r has_profile=%s",
            user_id,
            snapshot.major,
            bool(profile_data),
        )
        return snapshot

    async def _load_user(self, user_id: int) -> dict:
        async with AsyncSession(engine) as session:
            user = await session.get(User, user_id)
            if user is None:
                logger.warning("[ProfileSnapshot] 未找到用户基础信息: user_id=%s", user_id)
                return {"user_id": user_id}
            logger.info("[ProfileSnapshot] 已读取用户基础信息: user_id=%s username=%r", user_id, user.username)
            return {
                "user_id": user.id,
                "username": user.username,
                "major": user.major,
                "grade": user.grade,
                "school": user.school,
            }

    async def _load_profile(self, user_id: int) -> dict:
        profile = await memory_service.get_user_profile(user_id)
        if profile is None:
            logger.warning("[ProfileSnapshot] 未找到用户画像记录: user_id=%s", user_id)
            return {}
        data = profile.model_dump(exclude_none=True)
        updated_at = data.get("updated_at")
        if updated_at is not None:
            data["updated_at"] = updated_at.isoformat()
        logger.info("[ProfileSnapshot] 已读取用户画像: user_id=%s fields=%s", user_id, list(data.keys()))
        return data

    def build_personalized_context(
        self,
        snapshot: LearnerProfileSnapshot,
        task: dict,
    ) -> PersonalizedTaskContext:
        need = task.get("need", "review")
        difficulty = "intermediate"
        knowledge_score = snapshot.knowledge_level_score
        # 先用稳定评分给出默认难度，避免每个下游 Agent 再重复自行猜测。
        if knowledge_score is not None and knowledge_score < 40:
            difficulty = "basic"
        elif knowledge_score is not None and knowledge_score >= 75:
            difficulty = "advanced"

        explanation_style: list[str] = []
        if snapshot.cognitive_style:
            explanation_style.append(snapshot.cognitive_style)
        if need == "exam":
            explanation_style.append("考点优先，短时高频强化")
        elif need == "deep":
            explanation_style.append("强调原理推导与工程细节")
        else:
            explanation_style.append("先图解梳理，再精讲与练习")

        emphasis: list[str] = []
        if snapshot.error_pattern:
            emphasis.append(f"重点纠偏：{snapshot.error_pattern}")
        if snapshot.interest_preference:
            emphasis.append(f"案例偏好：{snapshot.interest_preference}")
        if task.get("extra"):
            emphasis.append(f"本次额外要求：{task['extra']}")

        context = PersonalizedTaskContext(
            course=task.get("course", ""),
            gap=task.get("gap", ""),
            need=need,
            extra=task.get("extra", ""),
            target_difficulty=difficulty,
            explanation_style=explanation_style,
            emphasis=emphasis,
            recommended_order=["content", "mindmap", "quiz", "reading", "code", "image", "ppt", "video"],
            profile_summary=snapshot.profile_summary,
        )
        logger.info(
            "[ProfileSnapshot] 个性化上下文已生成: need=%s difficulty=%s emphasis_count=%s",
            need,
            difficulty,
            len(context.emphasis),
        )
        return context
