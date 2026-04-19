from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    knowledge_level: Optional[str] = None
    knowledge_level_score: Optional[int] = None
    cognitive_style: Optional[str] = None
    cognitive_style_score: Optional[int] = None
    error_pattern: Optional[str] = None
    error_pattern_score: Optional[int] = None
    learning_goal: Optional[str] = None
    learning_goal_score: Optional[int] = None
    learning_history: Optional[str] = None
    learning_history_score: Optional[int] = None
    interest_preference: Optional[str] = None
    interest_preference_score: Optional[int] = None
    learning_pace: Optional[str] = None
    learning_pace_score: Optional[int] = None
    cognitive_level: Optional[str] = None
    cognitive_level_score: Optional[int] = None
    profile_summary: Optional[str] = None
    updated_at: Optional[datetime] = None


class ProfileHistoryItem(BaseModel):
    version: int
    knowledge_level: Optional[str] = None
    knowledge_level_score: Optional[int] = None
    cognitive_style: Optional[str] = None
    cognitive_style_score: Optional[int] = None
    error_pattern: Optional[str] = None
    error_pattern_score: Optional[int] = None
    learning_goal: Optional[str] = None
    learning_goal_score: Optional[int] = None
    learning_history: Optional[str] = None
    learning_history_score: Optional[int] = None
    interest_preference: Optional[str] = None
    interest_preference_score: Optional[int] = None
    learning_pace: Optional[str] = None
    learning_pace_score: Optional[int] = None
    cognitive_level: Optional[str] = None
    cognitive_level_score: Optional[int] = None
    profile_summary: Optional[str] = None
    change_reason: Optional[str] = None
    created_at: Optional[datetime] = None
