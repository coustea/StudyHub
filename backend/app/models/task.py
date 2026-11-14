from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text
from sqlmodel import Field, SQLModel

from app.models.base import utc_now


class Task(SQLModel, table=True):
    """视频生成与修改任务数据表模型（对应 MySQL tasks 表）。"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_project_created", "project_id", "created_at"),
        Index("idx_tasks_status_created", "status", "created_at"),
        Index("idx_tasks_request_message", "request_message_id"),
        CheckConstraint("type IN ('create', 'edit')", name="chk_tasks_type"),
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
            name="chk_tasks_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="chk_tasks_progress"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", ondelete="CASCADE")
    request_message_id: int | None = Field(
        default=None,
        foreign_key="messages.id",
        ondelete="SET NULL",
    )
    type: str = Field(default="create", max_length=20)
    status: str = Field(default="pending", max_length=20)
    phase: str = Field(default="pending", max_length=30)
    progress: int = Field(default=0)
    base_revision: int = Field(default=0)
    result_revision: int | None = Field(default=None)
    error_message: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utc_now},
    )
