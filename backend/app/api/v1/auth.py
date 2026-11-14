from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserPublic,
)
from app.services.auth import (
    authenticate_user,
    change_user_password,
    refresh_user_token,
    register_user,
    update_user_profile,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: SessionDep) -> UserPublic:
    """注册新用户并返回用户公开信息。"""
    return await register_user(session, request)


@router.post("/login")
async def login(request: LoginRequest, session: SessionDep) -> TokenResponse:
    """校验用户账号密码并返回 JWT 令牌。"""
    return await authenticate_user(session, request)


@router.post("/refresh")
async def refresh(request: RefreshRequest, session: SessionDep) -> TokenResponse:
    """使用刷新令牌换取新的访问令牌与刷新令牌。"""
    return await refresh_user_token(session, request)


@router.get("/me")
async def read_current_user(current_user: CurrentUserDep) -> UserPublic:
    """获取当前已认证用户的公开资料。"""
    return UserPublic.model_validate(current_user)


@router.patch("/me")
async def update_current_user_profile(
    request: UpdateProfileRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> UserPublic:
    """更新当前已认证用户的昵称或头像。"""
    return await update_user_profile(session, current_user, request)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    """校验原密码并修改当前用户登录密码。"""
    await change_user_password(session, current_user, request)
