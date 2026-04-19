"""Authentication adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.database import get_session
from app.config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET_KEY
from app.infra.models import ActiveToken
from app.infra.models import User

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


async def create_token(user_id: int, session: AsyncSession) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    token = jwt.encode(payload, JWT_SECRET_KEY or "dev-secret-change-in-production-long-enough", algorithm=JWT_ALGORITHM)
    session.add(ActiveToken(user_id=user_id, token=token, expires_at=expire))
    await session.commit()
    return token


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY or "dev-secret-change-in-production-long-enough",
            algorithms=[JWT_ALGORITHM],
        )
        return int(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token 已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效 Token") from exc


async def is_token_valid(token: str, session: AsyncSession) -> bool:
    active_token = (await session.exec(select(ActiveToken).where(ActiveToken.token == token))).first()
    if not active_token:
        return False
    if active_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await session.delete(active_token)
        await session.commit()
        return False
    return True


async def revoke_token(token: str, session: AsyncSession) -> None:
    active_token = (await session.exec(select(ActiveToken).where(ActiveToken.token == token))).first()
    if active_token:
        await session.delete(active_token)
        await session.commit()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = credentials.credentials
    if not await is_token_valid(token, session):
        raise HTTPException(status_code=401, detail="Token 已失效或已退出登录")
    user_id = decode_token(token)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    await session.refresh(user)
    return user
