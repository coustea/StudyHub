from datetime import datetime

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=50)
    email: str | None = Field(default=None, max_length=100)


class UserLogin(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=50)


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=100)
    avatar: str | None = Field(default=None, max_length=500)
    major: str | None = Field(default=None, max_length=100)
    grade: str | None = Field(default=None, max_length=20)
    school: str | None = Field(default=None, max_length=100)


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    email: str | None
    avatar: str | None
    major: str | None
    grade: str | None
    school: str | None
    created_at: datetime


class LoginResponse(BaseModel):
    token: str
    user: UserRead
