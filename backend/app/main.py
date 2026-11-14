import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# 直接以脚本方式运行（如 IDE 点击 Run backend/app/main.py）时补齐后端根目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and not __package__ and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: E402

from app.api.v1 import api_v1_router  # noqa: E402
from app.config.config import BACKEND_DIR, Settings, load_settings, set_settings  # noqa: E402
from app.core.exceptions import register_exception_handlers  # noqa: E402
from app.db.mysql import init_mysql  # noqa: E402
from app.db.redis import init_redis  # noqa: E402
from app.middleware.jwt_auth import JWTAuthMiddleware  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时初始化 MySQL 与 Redis 连接，退出时释放资源。"""
    cfg: Settings = app.state.settings
    engine, session_factory = await init_mysql(cfg, engine=app.state.engine)
    redis_client = await init_redis(cfg, client=app.state.redis)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    try:
        yield
    finally:
        await redis_client.aclose()
        await engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis_client: Redis | None = None,
) -> FastAPI:
    """加载系统配置并创建装配完成的 FastAPI 应用实例。

    Args:
        settings: 可选覆盖配置（主要用于测试环境隔离）。
        engine: 可选注入异步数据库引擎（用于测试环境隔离）。
        redis_client: 可选注入 Redis 客户端（用于测试替身）。

    Returns:
        配置完成的 FastAPI 实例。
    """
    cfg = settings or load_settings()
    set_settings(cfg)
    app = FastAPI(
        title=cfg.app.name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = cfg
    app.state.engine = engine
    app.state.redis = redis_client

    register_exception_handlers(app)

    # 注册纯 ASGI JWT 中间件，在进入受保护路由前完成令牌校验
    app.add_middleware(JWTAuthMiddleware)
    # CORS 中间件置于最外层，确保 401 等中间件响应也能携带跨域头
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router)
    return app


app = create_app()


def main() -> None:
    """读取应用配置并使用 Uvicorn 启动 FastAPI 服务。"""
    cfg: Settings = app.state.settings
    reload_enabled = cfg.app.debug
    uvicorn.run(
        "app.main:app" if reload_enabled else app,
        host=cfg.app.host,
        port=cfg.app.port,
        reload=reload_enabled,
        # 仅监听 app 目录，避免 workspaces 或 .venv 变更触发无意义热重载
        reload_dirs=[str(BACKEND_DIR / "app")] if reload_enabled else None,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
