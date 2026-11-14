from fastapi import Request
from redis.asyncio import Redis

from app.config.config import Settings


async def init_redis(
    settings: Settings,
    *,
    client: Redis | None = None,
) -> Redis:
    """初始化异步 Redis 客户端连接池并校验连通性。

    Args:
        settings: 应用配置实例。
        client: 可选外部注入客户端（用于测试替身）。

    Returns:
        可用的异步 Redis 客户端实例。
    """
    redis_cfg = settings.database.redis
    redis_client = client or Redis(
        host=redis_cfg.addr,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        encoding="utf-8",
        decode_responses=True,
    )
    await redis_client.ping()
    return redis_client


async def get_redis(request: Request) -> Redis:
    """从应用状态中提取异步 Redis 客户端依赖。"""
    return request.app.state.redis
