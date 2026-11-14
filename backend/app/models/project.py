from datetime import datetime

from sqlalchemy import DateTime, Index
from sqlmodel import Field, SQLModel

from app.models.base import utc_now


class Project(SQLModel, table=True):
    """视频项目数据表模型（对应 MySQL projects 表）。"""

    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_user_updated", "user_id", "updated_at"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    title: str = Field(max_length=200)
    current_revision: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utc_now},
    )
