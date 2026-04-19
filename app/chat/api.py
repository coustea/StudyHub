"""Chat HTTP routing."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.auth.security import get_current_user
from app.infra.models import User
from app.chat.service import get_chat_usecases
from app.shared.paths import WORKPLACE_DIR
from app.shared.response import HttpResponse

router = APIRouter()


@router.post("/chat/stream")
async def mentor_chat_stream(
    message: str = Form(...),
    session_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    file: UploadFile | None = File(default=None),
    image_urls: str | None = Form(default=None),
    file_urls: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式对话主入口。兼容多种附件传参（files/file/image_urls/file_urls）。"""
    uc = get_chat_usecases()
    upload_payloads: list[tuple[str, bytes]] = []
    all_uploads = list(files)
    if file is not None:
        all_uploads.append(file)

    for upload in all_uploads:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        upload_payloads.append((upload.filename, await upload.read()))

    parsed_image_urls: list[str] = []
    parsed_file_urls: list[str] = []
    if image_urls:
        parsed_image_urls = [u.strip() for u in image_urls.split(",") if u.strip()]
    if file_urls:
        parsed_file_urls = [u.strip() for u in file_urls.split(",") if u.strip()]

    try:
        effective_session, uploaded_image_urls, uploaded_file_urls = await uc.prepare_uploads(
            files=upload_payloads,
            user_id=current_user.id,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    merged_image_urls = uploaded_image_urls + parsed_image_urls
    merged_file_urls = uploaded_file_urls + parsed_file_urls

    # 返回 SSE 流式响应
    return StreamingResponse(
        uc.stream_chat(
            user_id=current_user.id,
            user_message=message,
            session_id=effective_session,
            image_urls=merged_image_urls or None,
            file_urls=merged_file_urls or None,
        ),
        media_type="text/event-stream",
    )


@router.post("/chat/upload")  # 独立上传接口（前端可先上传再发消息）
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        return HttpResponse.error(code=400, message="文件名不能为空")
    uc = get_chat_usecases()
    content = await file.read()
    try:
        saved = await uc.save_upload(
            filename=file.filename,
            content=content,
            user_id=current_user.id,
            session_id=session_id,
        )
    except ValueError as exc:
        return HttpResponse.error(code=400, message=str(exc))
    return HttpResponse.success(data=saved)


@router.get("/chat/uploads/{owner_id}/{session_id}/{filename}")  # 读取上传文件（带权限校验）
async def get_uploaded_file(
    owner_id: int,
    session_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
):
    uc = get_chat_usecases()
    try:
        file_path = uc.resolve_uploaded_file(
            current_user_id=current_user.id,
            owner_id=owner_id,
            session_id=session_id,
            filename=filename,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(path=str(file_path), filename=filename)


@router.get("/chat/sessions")
async def get_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    uc = get_chat_usecases()
    return HttpResponse.success(data=await uc.list_sessions(current_user.id, limit))


@router.post("/chat/sessions")
async def create_session(
    current_user: User = Depends(get_current_user),
):
    uc = get_chat_usecases()
    return HttpResponse.success(data=await uc.create_session(current_user.id))


@router.delete("/chat/sessions/{session_id}")  # 软删除：标记为归档而非物理删除
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    uc = get_chat_usecases()
    success = await uc.archive_session(current_user.id, session_id)
    if not success:
        return HttpResponse.error(code=404, message="会话不存在或无权操作")
    return HttpResponse.success(message="会话已归档")


@router.get("/chat/history")
async def chat_history(
    session_id: str | None = Query(default=None, description="指定会话ID"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    uc = get_chat_usecases()
    items = await uc.get_history(
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
    )
    return HttpResponse.success(data=[item.model_dump() for item in items])
