from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant"]


class CreateMessageRequest(BaseModel):
    """新增项目对话消息请求体。"""

    role: MessageRole
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class UpdateMessageRequest(BaseModel):
    """更新项目对话消息请求体（仅更新请求中显式传入的字段）。"""

    content: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = None


class MessagePublic(BaseModel):
    """对外暴露的对话消息结构。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    project_id: int
    role: MessageRole
    content: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class MessageListResponse(BaseModel):
    """项目对话消息分页列表响应体。"""

    items: list[MessagePublic]
    total: int
