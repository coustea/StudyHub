from typing import Annotated, NamedTuple

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import AuthenticationError
from app.db.mysql import get_session
from app.db.redis import get_redis
from app.models.user import User


class AuthIdentity(NamedTuple):
    """中间件从 JWT 解析并注入到请求状态中的当前用户标识。"""

    id: int
    username: str


SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_current_identity(request: Request) -> AuthIdentity:
    """直接从中间件注入的 request.state 获取当前用户 ID 与用户名（不查库）。"""
    user_id = getattr(request.state, "user_id", None)
    username = getattr(request.state, "username", None)
    if user_id is None or not username:
        raise AuthenticationError("未提供认证凭据。")
    return AuthIdentity(id=int(user_id), username=str(username))


async def get_current_user(
    identity: Annotated[AuthIdentity, Depends(get_current_identity)],
    session: SessionDep,
) -> User:
    """根据中间件注入的用户 ID 查询当前活跃用户完整记录。"""
    user = await session.get(User, identity.id)
    if user is None or not user.is_active:
        raise AuthenticationError("用户不存在或已被禁用。")
    return user


CurrentIdentityDep = Annotated[AuthIdentity, Depends(get_current_identity)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
