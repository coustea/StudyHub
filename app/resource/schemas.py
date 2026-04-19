from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LearningTask(BaseModel):
    course: str = Field(..., description="课程/主题")
    gap: str = Field(..., description="知识瓶颈/核心痛点")
    need: str = Field(default="review", description="资源偏好: exam/review/deep")
    extra: str = Field(default="", description="额外需求")


class ResourceGenerateRequest(BaseModel):
    learning_task: LearningTask
    selected_resources: Optional[list[str]] = Field(
        default=None,
        description="可选：指定要生成的资源类型；未传或为空时默认全量生成",
    )


class LearnerProfileSnapshot(BaseModel):
    user_id: int | None = None
    username: str | None = None
    major: str | None = None
    grade: str | None = None
    school: str | None = None

    knowledge_level: str | None = None
    knowledge_level_score: int | None = None
    learning_goal: str | None = None
    learning_goal_score: int | None = None
    learning_history: str | None = None
    learning_history_score: int | None = None
    cognitive_style: str | None = None
    cognitive_style_score: int | None = None
    error_pattern: str | None = None
    error_pattern_score: int | None = None
    learning_pace: str | None = None
    learning_pace_score: int | None = None
    interest_preference: str | None = None
    interest_preference_score: int | None = None
    cognitive_level: str | None = None
    cognitive_level_score: int | None = None
    profile_summary: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_sources(
        cls,
        user_data: dict[str, Any] | None = None,
        profile_data: dict[str, Any] | None = None,
    ) -> "LearnerProfileSnapshot":
        # 把用户基础信息和画像字段合并成运行时快照，避免下游直接耦合数据库模型。
        merged: dict[str, Any] = {}
        if user_data:
            merged.update(user_data)
        if profile_data:
            merged.update(profile_data)
        return cls.model_validate(merged)

    def as_agent_profile(self) -> dict[str, Any]:
        # Agent prompt 只需要非空字段，减少无意义的 null 噪音。
        return self.model_dump(exclude_none=True)


class PersonalizedTaskContext(BaseModel):
    course: str
    gap: str
    need: str = "review"
    extra: str = ""
    target_difficulty: str = "intermediate"
    explanation_style: list[str] = Field(default_factory=list)
    emphasis: list[str] = Field(default_factory=list)
    recommended_order: list[str] = Field(default_factory=list)
    profile_summary: str | None = None

    def as_prompt_context(self) -> dict[str, Any]:
        # 这里返回可序列化 dict，方便直接注入 planner prompt。
        return self.model_dump(exclude_none=True)


class ResourcePlan(BaseModel):
    core_agents: list[str] = Field(default_factory=list)
    enhancement_agents: list[str] = Field(default_factory=list)
    presentation_agents: list[str] = Field(default_factory=list)
    requested_agents: list[str] = Field(default_factory=list)
    execution_agents: list[str] = Field(default_factory=list)
    visible_agents: list[str] = Field(default_factory=list)
    hidden_dependency_agents: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    agent_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def ordered_agents(self) -> list[str]:
        # coordinator 用这个顺序统计总任务数和默认执行顺序。
        return self.core_agents + self.enhancement_agents + self.presentation_agents
