from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """用户注册请求体。"""

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    """用户登录请求体（支持用户名或邮箱登录）。"""

    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    """对外暴露的用户公开信息（过滤 password_hash 等敏感字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    display_name: str | None = None
    avatar_url: str | None = None
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class RefreshRequest(BaseModel):
    """刷新访问令牌请求体。"""

    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """登录或刷新成功后返回的 JWT 令牌响应体。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class UpdateProfileRequest(BaseModel):
    """更新当前用户公开资料请求体。"""

    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=512)


class ChangePasswordRequest(BaseModel):
    """修改当前用户登录密码请求体。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
