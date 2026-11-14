from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateProjectRequest(BaseModel):
    """创建视频项目请求体。"""

    title: str = Field(min_length=1, max_length=200)


class UpdateProjectRequest(BaseModel):
    """更新视频项目请求体（仅更新请求中显式传入的字段）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    current_revision: int | None = Field(default=None, ge=0)


class ProjectPublic(BaseModel):
    """对外暴露的视频项目详情结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    current_revision: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """项目分页列表响应体。"""

    items: list[ProjectPublic]
    total: int
