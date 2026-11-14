from pathlib import Path

from app.config.config import (
    BACKEND_DIR,
    CONFIG_YAML_PATH,
    DatabaseConfig,
    MysqlConfig,
    RedisConfig,
    Settings,
    load_settings,
)
from app.db.mysql import init_mysql
from app.db.redis import init_redis
from tests.conftest import FakeRedis


def test_load_settings_reads_config_yaml_and_dotenv_placeholders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JWT_SECRET_KEY=dotenv-secret-key-at-least-32-chars\n"
        "OPENAI_API_KEY=sk-test-dotenv\n"
        "MYSQL_PASSWORD=secret_mysql_pw\n"
        "REDIS_PASSWORD=\n"
        "TAVILY_API_KEY=tvly-test-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    settings = load_settings(yaml_path=CONFIG_YAML_PATH, env_path=env_file)
    assert settings.app.name == "FrameForge"
    assert settings.app.port == 8000
    assert settings.jwt.secret_key == "dotenv-secret-key-at-least-32-chars"
    assert settings.jwt.refresh_token_expire_days == 7
    assert settings.agent.llm.api_key == "sk-test-dotenv"
    assert settings.agent.llm.temperature == 0.7
    assert settings.agent.llm.max_tokens == 8192
    assert settings.agent.llm.timeout == 120.0
    assert settings.agent.llm.max_retries == 2
    assert settings.agent.tavily == "tvly-test-dotenv"
    assert settings.agent.workspace_dir == (BACKEND_DIR / "workspaces").resolve()
    assert settings.agent.skills_dir == (BACKEND_DIR / "app/agent/skills").resolve()
    assert settings.agent.workspaces == (BACKEND_DIR / "workspaces").resolve()
    assert settings.agent.skills == (BACKEND_DIR / "app/agent/skills").resolve()
    assert settings.database.mysql.host == "127.0.0.1"
    assert settings.database.mysql.password == "secret_mysql_pw"
    assert settings.database.mysql.pool_size == 10
    assert settings.database.redis.addr == "127.0.0.1"
    assert settings.database.redis.port == 6379
    assert settings.database.redis.password == ""


async def test_init_mysql_with_injected_sqlite_engine(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    sqlite_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")
    settings = Settings(
        database=DatabaseConfig(
            mysql=MysqlConfig(host="127.0.0.1", port=3306, database="frameforge"),
        )
    )
    engine, session_factory = await init_mysql(settings, engine=sqlite_engine)
    try:
        assert engine is sqlite_engine
        assert session_factory is not None
    finally:
        await engine.dispose()


async def test_startup_initializes_redis_and_closes_on_shutdown(
    app_instance,
    fake_redis: FakeRedis,
) -> None:
    assert fake_redis.ping_calls == 1
    assert app_instance.state.redis is fake_redis


async def test_local_redis_connection_ping() -> None:
    settings = Settings(
        database=DatabaseConfig(
            redis=RedisConfig(addr="127.0.0.1", port=6379, db=0),
        )
    )
    client = await init_redis(settings)
    try:
        conn_kwargs = client.connection_pool.connection_kwargs
        assert conn_kwargs["host"] == "127.0.0.1"
        assert conn_kwargs["port"] == 6379
        assert conn_kwargs["db"] == 0
    finally:
        await client.aclose()
