from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.message import Message
from app.models.project import Project
from app.models.task import Task
from app.schemas.project import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectPublic,
    UpdateProjectRequest,
)


async def get_owned_project(
    session: AsyncSession,
    project_id: int,
    user_id: int,
) -> Project:
    """查询并校验项目归属权，越权或不存在时统一抛出 404 防止资源枚举。"""
    project = (
        await session.exec(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
    ).first()
    if project is None:
        raise NotFoundError("项目不存在。")
    return project


async def create_project(
    session: AsyncSession,
    user_id: int,
    request: CreateProjectRequest,
) -> ProjectPublic:
    """为当前用户创建新的视频项目。

    Args:
        session: 异步数据库会话。
        user_id: 当前登录用户 ID。
        request: 创建项目请求参数。

    Returns:
        新建项目的公开详情。

    Raises:
        AppError: 标题去除空白后为空时抛出。
    """
    title = request.title.strip()
    if not title:
        raise AppError("项目标题不能为空。")

    project = Project(user_id=user_id, title=title)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectPublic.model_validate(project)


async def list_projects(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> ProjectListResponse:
    """分页查询当前用户的项目列表（按最近更新时间倒序）。"""
    total = (
        await session.exec(
            select(func.count()).select_from(Project).where(Project.user_id == user_id)
        )
    ).one()

    projects = (
        await session.exec(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.updated_at.desc(), Project.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return ProjectListResponse(
        items=[ProjectPublic.model_validate(project) for project in projects],
        total=int(total),
    )


async def get_project(
    session: AsyncSession,
    project_id: int,
    user_id: int,
) -> ProjectPublic:
    """查询当前用户的单个项目详情。"""
    project = await get_owned_project(session, project_id, user_id)
    return ProjectPublic.model_validate(project)


async def update_project(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    request: UpdateProjectRequest,
) -> ProjectPublic:
    """更新当前用户的项目标题或版本号。"""
    project = await get_owned_project(session, project_id, user_id)

    if "title" in request.model_fields_set:
        if request.title is None or not request.title.strip():
            raise AppError("项目标题不能为空。")
        project.title = request.title.strip()

    if "current_revision" in request.model_fields_set:
        if request.current_revision is None:
            raise AppError("项目版本号不能为空。")
        project.current_revision = request.current_revision

    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectPublic.model_validate(project)


async def delete_project(
    session: AsyncSession,
    project_id: int,
    user_id: int,
) -> None:
    """删除当前用户的项目，并显式清理关联的任务与对话消息记录。"""
    project = await get_owned_project(session, project_id, user_id)

    # 先清理子表记录，确保在未开启外键级联的测试库（如 SQLite）中行为一致
    await session.exec(delete(Task).where(Task.project_id == project.id))
    await session.exec(delete(Message).where(Message.project_id == project.id))
    await session.delete(project)
    await session.commit()
