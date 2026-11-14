from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import RedisDep, SessionDep

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """健康检查响应体（包含数据库与 Redis 连通状态）。"""

    status: str
    database: str
    redis: str


@router.get("")
async def health_check(session: SessionDep, redis: RedisDep) -> HealthResponse:
    """服务存活与基础设施连通性探针接口。"""
    await session.exec(text("SELECT 1"))
    await redis.ping()
    return HealthResponse(status="ok", database="ok", redis="ok")
