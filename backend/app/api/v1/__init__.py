from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.messages import router as messages_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(messages_router)
api_v1_router.include_router(tasks_router)
