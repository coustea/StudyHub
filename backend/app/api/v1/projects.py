from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import CurrentIdentityDep, SessionDep
from app.schemas.message import (
    CreateMessageRequest,
    MessageListResponse,
    MessagePublic,
)
from app.schemas.project import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectPublic,
    UpdateProjectRequest,
)
from app.schemas.task import (
    CreateTaskRequest,
    TaskListResponse,
    TaskPublic,
    TaskStatus,
)
from app.services.message import create_message, list_messages
from app.services.project import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)
from app.services.task import create_task, list_tasks

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectIdPath = Annotated[int, Path(ge=1, description="项目 ID")]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    request: CreateProjectRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> ProjectPublic:
    """为当前用户创建新项目。"""
    return await create_project(session, identity.id, request)


@router.get("")
async def list_projects_endpoint(
    identity: CurrentIdentityDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    """分页获取当前用户的项目列表。"""
    return await list_projects(session, identity.id, limit=limit, offset=offset)


@router.get("/{project_id}")
async def get_project_endpoint(
    project_id: ProjectIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> ProjectPublic:
    """获取当前用户的单个项目详情。"""
    return await get_project(session, project_id, identity.id)


@router.patch("/{project_id}")
async def update_project_endpoint(
    project_id: ProjectIdPath,
    request: UpdateProjectRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> ProjectPublic:
    """更新当前用户的项目标题或版本号。"""
    return await update_project(session, project_id, identity.id, request)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: ProjectIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> None:
    """删除当前用户的项目及关联消息和任务。"""
    await delete_project(session, project_id, identity.id)


@router.post("/{project_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_project_message_endpoint(
    project_id: ProjectIdPath,
    request: CreateMessageRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> MessagePublic:
    """在指定项目下新增一条对话消息。"""
    return await create_message(session, project_id, identity.id, request)


@router.get("/{project_id}/messages")
async def list_project_messages_endpoint(
    project_id: ProjectIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageListResponse:
    """分页查询指定项目的对话消息列表。"""
    return await list_messages(session, project_id, identity.id, limit=limit, offset=offset)


@router.post("/{project_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_project_task_endpoint(
    project_id: ProjectIdPath,
    request: CreateTaskRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> TaskPublic:
    """在指定项目下创建一条任务记录。"""
    return await create_task(session, project_id, identity.id, request)


@router.get("/{project_id}/tasks")
async def list_project_tasks_endpoint(
    project_id: ProjectIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskListResponse:
    """分页查询指定项目下的任务列表。"""
    return await list_tasks(
        session,
        project_id,
        identity.id,
        task_status=task_status,
        limit=limit,
        offset=offset,
    )
