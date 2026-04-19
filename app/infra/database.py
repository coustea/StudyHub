"""Database engine and session factory.

This is the single database bootstrap implementation used by the application.
Environment loading is handled in ``app.main`` only.

职责：
  - 校验数据库配置完整性
  - 创建全局异步引擎（连接池）
  - 提供表自动创建（init_db）和会话工厂（get_session）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import OperationalError
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import (
    APP_DEBUG,
    DB_ECHO,
    DB_HOST,
    DB_MAX_OVERFLOW,
    DB_NAME,
    DB_PASSWORD,
    DB_POOL_RECYCLE,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT,
    DB_PORT,
    DB_USER,
    DB_INIT_MAX_RETRIES,
    DB_INIT_RETRY_DELAY_SEC,
)
from app.infra.logging import get_logger
from app.infra.models import import_all_models

logger = get_logger(__name__)

RETRYABLE_MYSQL_ERROR_CODES = {
    2003,  # Can't connect to MySQL server
    2006,  # MySQL server has gone away
    2013,  # Lost connection to MySQL server during query
    2055,  # Lost connection to MySQL server at '%s', system error: %d
}


def _extract_mysql_error_code(exc: OperationalError) -> int | None:
    """从 sqlalchemy OperationalError 中提取 MySQL 错误码。"""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    if isinstance(args, tuple) and args:
        first = args[0]
        if isinstance(first, int):
            return first
    return None


def _validate_database_settings() -> None:
    """校验数据库必需配置项是否已设置，缺失则抛出 RuntimeError 阻止启动。"""
    missing = []
    if not DB_HOST:
        missing.append("DB_HOST")
    if not DB_PORT:
        missing.append("DB_PORT")
    if not DB_USER:
        missing.append("DB_USER")
    if not DB_PASSWORD:
        missing.append("DB_PASSWORD")
    if not DB_NAME:
        missing.append("DB_NAME")

    if missing:
        raise RuntimeError(
            "Missing required database settings: "
            + ", ".join(missing)
            + ". Load them through .env before starting the app."
        )
    logger.debug("[Database] 配置校验通过: host=%s:%d, db=%s, pool_size=%d",
                 DB_HOST, DB_PORT, DB_NAME, DB_POOL_SIZE)


# 模块加载时立即校验配置，确保问题在启动阶段暴露而非运行时
_validate_database_settings()

# 构建异步 MySQL 连接 URL（使用 aiomysql 驱动）
# quote_plus 对用户名和密码做 URL 编码，防止特殊字符导致解析错误
mysql_url = (
    "mysql+aiomysql://"
    f"{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# 创建全局异步引擎（所有服务共享同一个连接池）
engine = create_async_engine(
    mysql_url,
    echo=DB_ECHO,  # 是否打印 SQL 语句（开发调试用，生产环境应关闭）
    pool_pre_ping=True,  # 每次从连接池取连接时先 ping 一下，防止 MySQL 已断开
    pool_size=DB_POOL_SIZE,  # 连接池常驻连接数
    max_overflow=DB_MAX_OVERFLOW,  # 超出 pool_size 后允许临时创建的额外连接数
    pool_recycle=DB_POOL_RECYCLE,  # 连接最大存活时间（秒），超时自动回收重建
    pool_timeout=DB_POOL_TIMEOUT,  # 获取连接的超时时间（秒）
)


async def init_db() -> None:
    """创建数据库表。在应用启动时由 lifespan 调用。
    APP_DEBUG=true 时会先 DROP ALL 再 CREATE，仅用于开发环境。"""
    # 启动期数据库偶发抖动较常见，这里增加有限次重试，避免一次网络抖动导致服务直接退出。
    max_retries = DB_INIT_MAX_RETRIES
    retry_delay_sec = DB_INIT_RETRY_DELAY_SEC

    # 确保所有模型类被导入（触发 SQLModel 元数据注册）。
    # 放在重试循环外避免重复导入带来的噪音。
    import_all_models()

    async def _run_once() -> None:
        if APP_DEBUG:
            logger.warning("[Database] APP_DEBUG=true，将删除并重建所有表！")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "[Database] 开始初始化数据库: db=%s debug=%s attempt=%s/%s",
                DB_NAME,
                APP_DEBUG,
                attempt,
                max_retries,
            )
            await _run_once()
            logger.info(
                "[Database] 数据库表初始化完成: db=%s, debug=%s, attempt=%s/%s",
                DB_NAME,
                APP_DEBUG,
                attempt,
                max_retries,
            )
            return
        except OperationalError as exc:
            mysql_code = _extract_mysql_error_code(exc)
            if mysql_code is not None and mysql_code not in RETRYABLE_MYSQL_ERROR_CODES:
                logger.error(
                    "[Database] 初始化失败（非重试型错误）: db=%s mysql_code=%s error=%s",
                    DB_NAME,
                    mysql_code,
                    exc,
                )
                raise
            if attempt >= max_retries:
                logger.exception(
                    "[Database] 初始化失败且重试耗尽: db=%s attempts=%s error=%s",
                    DB_NAME,
                    max_retries,
                    exc,
                )
                raise
            logger.warning(
                "[Database] 初始化失败，准备重试: db=%s attempt=%s/%s retry_after=%.1fs error=%s",
                DB_NAME,
                attempt,
                max_retries,
                retry_delay_sec,
                exc,
            )
            await asyncio.sleep(retry_delay_sec)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用的会话工厂（async generator 形式）。
    expire_on_commit=False 防止 commit 后访问属性触发懒加载报错。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
