from sqlalchemy import func
from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.message import Message
from app.models.project import Project
from app.models.task import Task
from app.schemas.message import (
    CreateMessageRequest,
    MessageListResponse,
    MessagePublic,
    UpdateMessageRequest,
)
from app.services.project import get_owned_project


async def _get_owned_message(
    session: AsyncSession,
    message_id: int,
    user_id: int,
) -> Message:
    """按所属项目校验消息归属权，越权或不存在时统一返回 404。"""
    message = (
        await session.exec(
            select(Message)
            .join(Project, Message.project_id == Project.id)
            .where(Message.id == message_id, Project.user_id == user_id)
        )
    ).first()
    if message is None:
        raise NotFoundError("消息不存在。")
    return message


async def create_message(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    request: CreateMessageRequest,
) -> MessagePublic:
    """在指定项目下创建一条对话消息。"""
    await get_owned_project(session, project_id, user_id)

    content = request.content.strip()
    if not content:
        raise AppError("消息内容不能为空。")

    message = Message(
        project_id=project_id,
        role=request.role,
        content=content,
        metadata_=request.metadata,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return MessagePublic.model_validate(message)


async def list_messages(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> MessageListResponse:
    """分页查询项目的对话历史消息（按消息 ID 升序排列）。"""
    await get_owned_project(session, project_id, user_id)

    total = (
        await session.exec(
            select(func.count()).select_from(Message).where(Message.project_id == project_id)
        )
    ).one()

    messages = (
        await session.exec(
            select(Message)
            .where(Message.project_id == project_id)
            .order_by(Message.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return MessageListResponse(
        items=[MessagePublic.model_validate(message) for message in messages],
        total=int(total),
    )


async def get_message(
    session: AsyncSession,
    message_id: int,
    user_id: int,
) -> MessagePublic:
    """查询当前用户项目下的单条消息详情。"""
    message = await _get_owned_message(session, message_id, user_id)
    return MessagePublic.model_validate(message)


async def update_message(
    session: AsyncSession,
    message_id: int,
    user_id: int,
    request: UpdateMessageRequest,
) -> MessagePublic:
    """更新消息文本内容或扩展元数据。"""
    message = await _get_owned_message(session, message_id, user_id)

    if "content" in request.model_fields_set:
        if request.content is None or not request.content.strip():
            raise AppError("消息内容不能为空。")
        message.content = request.content.strip()

    if "metadata" in request.model_fields_set:
        message.metadata_ = request.metadata

    session.add(message)
    await session.commit()
    await session.refresh(message)
    return MessagePublic.model_validate(message)


async def delete_message(
    session: AsyncSession,
    message_id: int,
    user_id: int,
) -> None:
    """删除单条对话消息，并解除任务表中的外键关联。"""
    message = await _get_owned_message(session, message_id, user_id)

    # 与 schema.sql 的 ON DELETE SET NULL 对齐，保证测试环境与生产环境一致
    await session.exec(
        update(Task)
        .where(Task.request_message_id == message.id)
        .values(request_message_id=None)
    )
    await session.delete(message)
    await session.commit()
