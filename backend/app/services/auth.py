from datetime import UTC, datetime

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import AppError, AuthenticationError, ConflictError
from app.core.security import (
    create_tokens,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserPublic,
)


def _issue_token_response(user: User) -> TokenResponse:
    """为已认证用户签发访问令牌与刷新令牌，并构造响应体。"""
    if user.id is None:
        raise AuthenticationError("用户状态异常。")

    access_token, refresh_token, expires_in = create_tokens(
        user_id=user.id,
        username=user.username,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserPublic.model_validate(user),
    )


async def register_user(
    session: AsyncSession,
    request: RegisterRequest,
) -> UserPublic:
    """注册新用户并返回公开用户信息（仅创建账号，不签发令牌）。

    Args:
        session: 异步数据库会话。
        request: 注册请求参数。

    Returns:
        新建用户的公开信息模型。

    Raises:
        ConflictError: 用户名或邮箱已被占用时抛出。
    """
    normalized_username = request.username.strip()
    normalized_email = request.email.strip().lower()

    existing = (
        await session.exec(
            select(User).where(
                or_(
                    User.username == normalized_username,
                    User.email == normalized_email,
                )
            )
        )
    ).first()
    if existing is not None:
        if existing.username == normalized_username:
            raise ConflictError("用户名已被注册。")
        raise ConflictError("邮箱已被注册。")

    display_name = (
        request.display_name.strip() if request.display_name else normalized_username
    )
    user = User(
        username=normalized_username,
        email=normalized_email,
        password_hash=hash_password(request.password),
        display_name=display_name,
        role="user",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return UserPublic.model_validate(user)


async def authenticate_user(
    session: AsyncSession,
    request: LoginRequest,
) -> TokenResponse:
    """校验用户登录凭据并签发 JWT 令牌对。

    Args:
        session: 异步数据库会话。
        request: 登录请求参数（支持用户名或邮箱）。

    Returns:
        包含访问令牌、刷新令牌与公开用户信息的响应对象。

    Raises:
        AuthenticationError: 账号不存在、密码错误或账号被禁用时抛出。
    """
    identifier = request.identifier.strip()
    normalized_email = identifier.lower()

    user = (
        await session.exec(
            select(User).where(
                or_(
                    User.username == identifier,
                    User.email == normalized_email,
                )
            )
        )
    ).first()

    if user is None or not verify_password(request.password, user.password_hash):
        raise AuthenticationError("用户名/邮箱或密码错误。")

    if not user.is_active:
        raise AuthenticationError("用户账号已被禁用。")

    user.last_login_at = datetime.now(UTC)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return _issue_token_response(user)


async def refresh_user_token(
    session: AsyncSession,
    request: RefreshRequest,
) -> TokenResponse:
    """校验刷新令牌并为用户签发新的访问令牌与刷新令牌。

    Args:
        session: 异步数据库会话。
        request: 刷新令牌请求参数。

    Returns:
        包含新访问令牌、刷新令牌与公开用户信息的响应对象。

    Raises:
        AuthenticationError: 刷新令牌无效、过期或用户不可用时抛出。
    """
    user_id, _ = decode_token(request.refresh_token, expected_type="refresh")
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("用户不存在或已被禁用。")

    return _issue_token_response(user)


async def update_user_profile(
    session: AsyncSession,
    user: User,
    request: UpdateProfileRequest,
) -> UserPublic:
    """更新当前用户的昵称与头像地址（仅修改显式传入的字段）。

    Args:
        session: 异步数据库会话。
        user: 当前已认证的用户模型。
        request: 资料更新请求参数。

    Returns:
        更新后的用户公开信息。
    """
    if "display_name" in request.model_fields_set:
        cleaned_name = request.display_name.strip() if request.display_name is not None else None
        user.display_name = cleaned_name or None
    if "avatar_url" in request.model_fields_set:
        cleaned_avatar = request.avatar_url.strip() if request.avatar_url is not None else None
        user.avatar_url = cleaned_avatar or None

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserPublic.model_validate(user)


async def change_user_password(
    session: AsyncSession,
    user: User,
    request: ChangePasswordRequest,
) -> None:
    """校验旧密码并更新当前用户的登录密码。

    Args:
        session: 异步数据库会话。
        user: 当前已认证的用户模型。
        request: 修改密码请求参数。

    Raises:
        AuthenticationError: 旧密码校验失败时抛出。
        AppError: 新密码与旧密码相同时抛出。
    """
    if not verify_password(request.old_password, user.password_hash):
        raise AuthenticationError("原密码错误。")

    if request.old_password == request.new_password:
        raise AppError("新密码不能与原密码相同。")

    user.password_hash = hash_password(request.new_password)
    session.add(user)
    await session.commit()
