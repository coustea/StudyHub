from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskType = Literal["create", "edit"]
TaskStatus = Literal["pending", "running", "success", "failed", "cancelled"]
TaskPhase = Literal["pending", "plan", "code", "validate", "repair", "render", "completed"]


class CreateTaskRequest(BaseModel):
    """创建视频任务请求体。"""

    type: TaskType = "create"
    request_message_id: int | None = Field(default=None, ge=1)
    base_revision: int = Field(default=0, ge=0)


class UpdateTaskRequest(BaseModel):
    """更新视频任务状态与进度请求体（仅更新请求中显式传入的字段）。"""

    status: TaskStatus | None = None
    phase: TaskPhase | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    result_revision: int | None = Field(default=None, ge=0)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskPublic(BaseModel):
    """对外暴露的视频任务详情结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    request_message_id: int | None = None
    type: TaskType
    status: TaskStatus
    phase: TaskPhase
    progress: int
    base_revision: int
    result_revision: int | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class TaskListResponse(BaseModel):
    """视频任务分页列表响应体。"""

    items: list[TaskPublic]
    total: int
