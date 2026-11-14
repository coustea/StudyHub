from datetime import UTC, datetime

from sqlalchemy import DateTime, Index
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(UTC)


class User(SQLModel, table=True):
    """平台注册用户数据表模型（对应 MySQL users 表）。"""

    __tablename__ = "users"
    __table_args__ = (Index("idx_users_role_active", "role", "is_active"),)

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(max_length=64, unique=True)
    email: str = Field(max_length=255, unique=True)
    password_hash: str = Field(max_length=255)
    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=512)
    role: str = Field(default="user", max_length=20)
    is_active: bool = Field(default=True)
    last_login_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    created_at: datetime = Field(
        default_factory=_utc_now, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": _utc_now},
    )
