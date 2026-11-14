from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import CurrentIdentityDep, SessionDep
from app.schemas.task import TaskPublic, UpdateTaskRequest
from app.services.task import delete_task, get_task, update_task

router = APIRouter(prefix="/tasks", tags=["tasks"])

TaskIdPath = Annotated[int, Path(ge=1, description="任务 ID")]


@router.get("/{task_id}")
async def get_task_endpoint(
    task_id: TaskIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> TaskPublic:
    """获取单条任务详情。"""
    return await get_task(session, task_id, identity.id)


@router.patch("/{task_id}")
async def update_task_endpoint(
    task_id: TaskIdPath,
    request: UpdateTaskRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> TaskPublic:
    """更新任务状态、阶段、进度或产物版本号。"""
    return await update_task(session, task_id, identity.id, request)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: TaskIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> None:
    """删除单条任务记录。"""
    await delete_task(session, task_id, identity.id)
