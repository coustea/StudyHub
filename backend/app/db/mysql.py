from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.config import Settings


async def init_mysql(
    settings: Settings,
    *,
    engine: AsyncEngine | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """初始化异步 MySQL 引擎与会话工厂，并校验数据库连通性。

    Args:
        settings: 应用配置实例。
        engine: 可选外部注入引擎（主要用于测试环境隔离）。

    Returns:
        由 (AsyncEngine, async_sessionmaker) 组成的二元组。
    """
    mysql = settings.database.mysql
    target_engine = engine
    if target_engine is None:
        url = URL.create(
            drivername="mysql+aiomysql",
            username=mysql.username,
            password=mysql.password or None,
            host=mysql.host,
            port=mysql.port,
            database=mysql.database,
            query={"charset": "utf8mb4"},
        )
        target_engine = create_async_engine(
            url,
            pool_size=mysql.pool_size,
            max_overflow=mysql.max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

    async with target_engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    session_factory = async_sessionmaker(
        bind=target_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return target_engine, session_factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """按请求作用域提供异步 SQLModel 数据库会话。"""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
