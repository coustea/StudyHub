from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.config import AppConfig, JwtConfig, Settings
from app.db.base import target_metadata
from app.main import create_app


class FakeRedis:
    """测试用轻量内存 Redis 替身，避免单元测试污染外部 Redis 实例。"""

    def __init__(self) -> None:
        self.closed = False
        self.ping_calls = 0

    async def ping(self) -> bool:
        self.ping_calls += 1
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app=AppConfig(env="test", debug=False),
        jwt=JwtConfig(
            secret_key="test-jwt-secret-key-must-be-at-least-32-bytes-long",
            access_token_expire_minutes=30,
        ),
    )


@pytest.fixture
async def app_instance(tmp_path: Path, test_settings: Settings, fake_redis: FakeRedis):
    db_file = tmp_path / "test_frameforge.db"
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(target_metadata.create_all)
    app = create_app(
        settings=test_settings,
        engine=test_engine,
        redis_client=fake_redis,
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
def async_session_factory(
    app_instance,
) -> async_sessionmaker[AsyncSession]:
    return app_instance.state.session_factory


@pytest.fixture
async def client(app_instance) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
