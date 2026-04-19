"""Auth service — 用户账号存储 + 认证用例。"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.security import create_token, hash_password, verify_password, revoke_token
from app.infra.models import User
from app.auth.schemas import UserRead


class UserAccountStore:
    """用户账号持久化。"""

    async def register(self, session: AsyncSession, data) -> dict | None:
        existing = (await session.exec(select(User).where(User.username == data.username))).first()
        if existing:
            return None
        user = User(
            username=data.username,
            password=hash_password(data.password),
            email=data.email,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return {"user": UserRead.model_validate(user)}

    async def authenticate(self, session: AsyncSession, username: str, password: str) -> dict | None:
        user = (await session.exec(select(User).where(User.username == username))).first()
        if not user:
            return None
        await session.refresh(user)
        if not verify_password(password, user.password):
            return None
        token = await create_token(user.id, session)
        return {"token": token, "user": UserRead.model_validate(user)}

    async def update(self, session: AsyncSession, user_id: int, data) -> User | None:
        user = await session.get(User, user_id)
        if not user:
            return None
        await session.refresh(user)
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return user
        user.sqlmodel_update(update_data)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


class AuthUseCases:
    """认证相关用例：注册、登录、登出、更新。"""

    def __init__(self, account_store: UserAccountStore) -> None:
        self.account_store = account_store

    async def register(self, session: AsyncSession, data):
        return await self.account_store.register(session, data)

    async def login(self, session: AsyncSession, data):
        return await self.account_store.authenticate(session, data.username, data.password)

    async def update_me(self, session: AsyncSession, user_id: int, data):
        return await self.account_store.update(session, user_id, data)

    async def logout(self, session: AsyncSession, token: str) -> None:
        await revoke_token(token, session)

    async def build_profile_on_logout(self, user_id: int) -> None:
        """登出后触发画像构建（懒加载 profile runtime）。"""
        from app.profile.service import learner_profile_runtime
        await learner_profile_runtime.build_profile(user_id=user_id)


# 模块级单例
account_store = UserAccountStore()
auth_usecases = AuthUseCases(account_store)
