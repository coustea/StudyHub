from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.message import Message
from app.models.project import Project
from app.models.task import Task
from app.schemas.task import (
    CreateTaskRequest,
    TaskListResponse,
    TaskPublic,
    TaskStatus,
    UpdateTaskRequest,
)
from app.services.project import get_owned_project


async def _get_owned_task(
    session: AsyncSession,
    task_id: int,
    user_id: int,
) -> Task:
    """按所属项目校验任务归属权，越权或不存在时统一返回 404。"""
    task = (
        await session.exec(
            select(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Task.id == task_id, Project.user_id == user_id)
        )
    ).first()
    if task is None:
        raise NotFoundError("任务不存在。")
    return task


async def create_task(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    request: CreateTaskRequest,
) -> TaskPublic:
    """在指定项目下创建一条任务记录。"""
    await get_owned_project(session, project_id, user_id)

    if request.request_message_id is not None:
        message = (
            await session.exec(
                select(Message).where(
                    Message.id == request.request_message_id,
                    Message.project_id == project_id,
                )
            )
        ).first()
        if message is None:
            raise NotFoundError("关联的消息不存在。")

    task = Task(
        project_id=project_id,
        request_message_id=request.request_message_id,
        type=request.type,
        base_revision=request.base_revision,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return TaskPublic.model_validate(task)


async def list_tasks(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    *,
    task_status: TaskStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> TaskListResponse:
    """分页查询项目下的任务列表（支持按状态筛选，按创建时间倒序）。"""
    await get_owned_project(session, project_id, user_id)

    conditions = [Task.project_id == project_id]
    if task_status is not None:
        conditions.append(Task.status == task_status)

    total = (
        await session.exec(select(func.count()).select_from(Task).where(*conditions))
    ).one()

    tasks = (
        await session.exec(
            select(Task)
            .where(*conditions)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return TaskListResponse(
        items=[TaskPublic.model_validate(task) for task in tasks],
        total=int(total),
    )


async def get_task(
    session: AsyncSession,
    task_id: int,
    user_id: int,
) -> TaskPublic:
    """查询当前用户项目下的单条任务详情。"""
    task = await _get_owned_task(session, task_id, user_id)
    return TaskPublic.model_validate(task)


async def update_task(
    session: AsyncSession,
    task_id: int,
    user_id: int,
    request: UpdateTaskRequest,
) -> TaskPublic:
    """更新任务的状态、阶段、进度、产物版本或时间信息。"""
    task = await _get_owned_task(session, task_id, user_id)

    non_null_fields = {"status", "phase", "progress"}
    for field_name in request.model_fields_set:
        value = getattr(request, field_name)
        if field_name in non_null_fields and value is None:
            raise AppError(f"字段 {field_name} 不能为空。")
        setattr(task, field_name, value)

    session.add(task)
    await session.commit()
    await session.refresh(task)
    return TaskPublic.model_validate(task)


async def delete_task(
    session: AsyncSession,
    task_id: int,
    user_id: int,
) -> None:
    """删除单条任务记录。"""
    task = await _get_owned_task(session, task_id, user_id)
    await session.delete(task)
    await session.commit()
