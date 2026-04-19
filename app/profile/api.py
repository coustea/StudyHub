"""Profile HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.security import get_current_user
from app.infra.models import User
from app.profile.service import profile_usecases
from app.profile.schemas import ProfileHistoryItem, ProfileResponse
from app.shared.response import HttpResponse

router = APIRouter()


@router.get("/profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
):
    profile = await profile_usecases.get_profile(current_user.id)
    if not profile:
        return HttpResponse.success(data=None, message="暂无画像数据")
    data = ProfileResponse(
        knowledge_level=profile.knowledge_level,
        knowledge_level_score=profile.knowledge_level_score,
        cognitive_style=profile.cognitive_style,
        cognitive_style_score=profile.cognitive_style_score,
        error_pattern=profile.error_pattern,
        error_pattern_score=profile.error_pattern_score,
        learning_goal=profile.learning_goal,
        learning_goal_score=profile.learning_goal_score,
        learning_history=profile.learning_history,
        learning_history_score=profile.learning_history_score,
        interest_preference=profile.interest_preference,
        interest_preference_score=profile.interest_preference_score,
        learning_pace=profile.learning_pace,
        learning_pace_score=profile.learning_pace_score,
        cognitive_level=profile.cognitive_level,
        cognitive_level_score=profile.cognitive_level_score,
        profile_summary=profile.profile_summary,
        updated_at=profile.updated_at,
    )
    return HttpResponse.success(data=data)


@router.get("/profile/history")
async def get_profile_history(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    history = await profile_usecases.get_profile_history(current_user.id, limit)
    if not history:
        return HttpResponse.success(data=[], message="暂无变更历史")
    items = [
        ProfileHistoryItem(
            version=value.version,
            knowledge_level=value.knowledge_level,
            knowledge_level_score=value.knowledge_level_score,
            cognitive_style=value.cognitive_style,
            cognitive_style_score=value.cognitive_style_score,
            error_pattern=value.error_pattern,
            error_pattern_score=value.error_pattern_score,
            learning_goal=value.learning_goal,
            learning_goal_score=value.learning_goal_score,
            learning_history=value.learning_history,
            learning_history_score=value.learning_history_score,
            interest_preference=value.interest_preference,
            interest_preference_score=value.interest_preference_score,
            learning_pace=value.learning_pace,
            learning_pace_score=value.learning_pace_score,
            cognitive_level=value.cognitive_level,
            cognitive_level_score=value.cognitive_level_score,
            profile_summary=value.profile_summary,
            change_reason=value.change_reason,
            created_at=value.created_at,
        )
        for value in history
    ]
    return HttpResponse.success(data=items)
