from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Index, Text
from sqlmodel import Field, SQLModel

from app.models.base import utc_now


class Message(SQLModel, table=True):
    """项目对话消息数据表模型（对应 MySQL messages 表）。"""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_project_id", "project_id", "id"),
        CheckConstraint("role IN ('user', 'assistant')", name="chk_messages_role"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", ondelete="CASCADE")
    role: str = Field(max_length=20)
    content: str = Field(sa_type=Text)
    # SQLAlchemy 保留了类属性 metadata，模型字段使用 metadata_ 映射到原列名
    metadata_: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column("metadata", JSON, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
    )
