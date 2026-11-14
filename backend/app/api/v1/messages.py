from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import CurrentIdentityDep, SessionDep
from app.schemas.message import MessagePublic, UpdateMessageRequest
from app.services.message import delete_message, get_message, update_message

router = APIRouter(prefix="/messages", tags=["messages"])

MessageIdPath = Annotated[int, Path(ge=1, description="消息 ID")]


@router.get("/{message_id}")
async def get_message_endpoint(
    message_id: MessageIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> MessagePublic:
    """获取单条对话消息详情。"""
    return await get_message(session, message_id, identity.id)


@router.patch("/{message_id}")
async def update_message_endpoint(
    message_id: MessageIdPath,
    request: UpdateMessageRequest,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> MessagePublic:
    """更新单条对话消息的内容或元数据。"""
    return await update_message(session, message_id, identity.id, request)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_endpoint(
    message_id: MessageIdPath,
    identity: CurrentIdentityDep,
    session: SessionDep,
) -> None:
    """删除单条对话消息。"""
    await delete_message(session, message_id, identity.id)
