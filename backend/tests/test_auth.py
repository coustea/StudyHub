from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentIdentityDep
from app.config.config import Settings
from app.models.user import User


async def _register_and_login(
    client: AsyncClient,
    *,
    username: str,
    email: str,
    password: str,
    display_name: str | None = None,
) -> dict:
    """测试辅助函数：先注册账号再通过登录接口获取 JWT 令牌。"""
    reg_payload = {"username": username, "email": email, "password": password}
    if display_name is not None:
        reg_payload["display_name"] = display_name

    reg_res = await client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_res.status_code == 201

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": password},
    )
    assert login_res.status_code == 200
    return login_res.json()


async def test_startup_loads_db_without_auto_migrations(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with async_session_factory() as session:
        result = await session.exec(text("SELECT 1"))
        assert result.one()[0] == 1


async def test_health_endpoint_is_public(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_register_creates_user_without_issuing_tokens(
    client: AsyncClient,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payload = {
        "username": "alice_cs",
        "email": "Alice@Example.com",
        "password": "StrongPassword123!",
        "display_name": "Alice",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert "access_token" not in data
    assert "refresh_token" not in data
    assert data["username"] == "alice_cs"
    assert data["email"] == "alice@example.com"
    assert data["display_name"] == "Alice"
    assert data["last_login_at"] is None
    assert "password_hash" not in data

    async with async_session_factory() as session:
        db_user = (await session.exec(select(User).where(User.username == "alice_cs"))).first()
        assert db_user is not None
        assert db_user.password_hash != payload["password"]
        assert db_user.password_hash.startswith("$argon2")


async def test_register_duplicate_username_or_email_returns_409(
    client: AsyncClient,
) -> None:
    first = {
        "username": "bob_dev",
        "email": "bob@example.com",
        "password": "StrongPassword123!",
    }
    res1 = await client.post("/api/v1/auth/register", json=first)
    assert res1.status_code == 201

    dup_username = {
        "username": "bob_dev",
        "email": "bob2@example.com",
        "password": "StrongPassword123!",
    }
    res2 = await client.post("/api/v1/auth/register", json=dup_username)
    assert res2.status_code == 409

    dup_email = {
        "username": "bob_other",
        "email": "BOB@example.com",
        "password": "StrongPassword123!",
    }
    res3 = await client.post("/api/v1/auth/register", json=dup_email)
    assert res3.status_code == 409


async def test_login_by_username_and_email_creates_tokens(
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "charlie",
            "email": "charlie@example.com",
            "password": "SecretPass999!",
        },
    )

    res_username = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "charlie", "password": "SecretPass999!"},
    )
    assert res_username.status_code == 200
    data = res_username.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] == 1800

    claims = jwt.decode(
        data["access_token"],
        test_settings.jwt.secret_key,
        algorithms=[test_settings.jwt.algorithm],
    )
    assert claims["sub"] == str(data["user"]["id"])
    assert claims["username"] == "charlie"
    assert claims["type"] == "access"

    res_email = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "CHARLIE@example.com", "password": "SecretPass999!"},
    )
    assert res_email.status_code == 200
    assert res_email.json()["user"]["username"] == "charlie"


async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "dana",
            "email": "dana@example.com",
            "password": "CorrectPassword1!",
        },
    )

    res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "dana", "password": "WrongPassword!"},
    )
    assert res.status_code == 401
    assert res.headers.get("www-authenticate") == "Bearer"


async def test_jwt_middleware_protects_and_injects_identity(
    app_instance,
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    @app_instance.get("/api/v1/_test/identity")
    async def read_identity(identity: CurrentIdentityDep) -> dict[str, int | str]:
        return {"id": identity.id, "username": identity.username}

    unauth = await client.get("/api/v1/auth/me")
    assert unauth.status_code == 401
    assert unauth.headers.get("www-authenticate") == "Bearer"

    bad_scheme = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Basic abcdef"},
    )
    assert bad_scheme.status_code == 401

    expired_token = jwt.encode(
        {
            "sub": "1",
            "username": "expired_user",
            "type": "access",
            "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
        },
        test_settings.jwt.secret_key,
        algorithm=test_settings.jwt.algorithm,
    )
    expired_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert expired_res.status_code == 401

    tokens = await _register_and_login(
        client,
        username="eve_ml",
        email="eve@example.com",
        password="StrongPassword123!",
    )

    # refresh_token 不能当作 access_token 调用受保护接口
    wrong_type_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert wrong_type_res.status_code == 401

    identity_res = await client.get(
        "/api/v1/_test/identity",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert identity_res.status_code == 200
    assert identity_res.json() == {
        "id": tokens["user"]["id"],
        "username": "eve_ml",
    }

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "eve_ml"
    assert me_res.json()["email"] == "eve@example.com"


async def test_refresh_token_flow_and_validation(
    client: AsyncClient,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tokens = await _register_and_login(
        client,
        username="grace_jwt",
        email="grace@example.com",
        password="StrongPassword123!",
    )

    # access_token 不能用于 /refresh 接口
    wrong_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )
    assert wrong_res.status_code == 401

    refresh_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_res.status_code == 200
    refreshed = refresh_res.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]
    assert refreshed["user"]["username"] == "grace_jwt"

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed['access_token']}"},
    )
    assert me_res.status_code == 200

    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.username == "grace_jwt"))).one()
        user.is_active = False
        session.add(user)
        await session.commit()

    disabled_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refreshed["refresh_token"]},
    )
    assert disabled_res.status_code == 401


async def test_inactive_user_cannot_login_or_access_me(
    client: AsyncClient,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tokens = await _register_and_login(
        client,
        username="frank",
        email="frank@example.com",
        password="StrongPassword123!",
    )

    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.username == "frank"))).one()
        user.is_active = False
        session.add(user)
        await session.commit()

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_res.status_code == 401

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "frank", "password": "StrongPassword123!"},
    )
    assert login_res.status_code == 401


async def test_update_profile_and_change_password(client: AsyncClient) -> None:
    tokens = await _register_and_login(
        client,
        username="henry",
        email="henry@example.com",
        password="OldPassword123!",
        display_name="Henry",
    )
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # 仅更新头像时应保留原昵称
    patch_avatar = await client.patch(
        "/api/v1/auth/me",
        json={"avatar_url": "https://example.com/avatar.png"},
        headers=headers,
    )
    assert patch_avatar.status_code == 200
    assert patch_avatar.json()["display_name"] == "Henry"
    assert patch_avatar.json()["avatar_url"] == "https://example.com/avatar.png"

    # 仅更新昵称时应保留头像
    patch_name = await client.patch(
        "/api/v1/auth/me",
        json={"display_name": "Henry Updated"},
        headers=headers,
    )
    assert patch_name.status_code == 200
    assert patch_name.json()["display_name"] == "Henry Updated"
    assert patch_name.json()["avatar_url"] == "https://example.com/avatar.png"

    # 原密码错误返回 401
    wrong_old = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "WrongPassword!", "new_password": "NewPassword123!"},
        headers=headers,
    )
    assert wrong_old.status_code == 401

    # 新旧密码一致返回 400
    same_pwd = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "OldPassword123!", "new_password": "OldPassword123!"},
        headers=headers,
    )
    assert same_pwd.status_code == 400

    # 正常修改密码
    ok_res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "OldPassword123!", "new_password": "NewPassword123!"},
        headers=headers,
    )
    assert ok_res.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "henry", "password": "OldPassword123!"},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "henry", "password": "NewPassword123!"},
    )
    assert new_login.status_code == 200
