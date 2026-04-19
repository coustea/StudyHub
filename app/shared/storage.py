"""Local filesystem storage adapter."""
from __future__ import annotations

import uuid
from pathlib import Path

from app.chat.schemas import UploadResponse
from app.shared.paths import WORKPLACE_DIR


class LocalFileStore:
    def __init__(self) -> None:
        self.upload_dir = WORKPLACE_DIR / "chat-uploads"
        self.allowed_image_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        self.allowed_doc_ext = {".pdf", ".docx", ".txt", ".md", ".log", ".xlsx", ".xls", ".csv", ".tsv"}
        self.max_image_size = 5 * 1024 * 1024
        self.max_doc_size = 10 * 1024 * 1024

    def ensure_roots(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        *,
        filename: str,
        content: bytes,
        user_id: int,
        session_id: str,
    ) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix in self.allowed_image_ext:
            file_type = "image"
            max_size = self.max_image_size
        elif suffix in self.allowed_doc_ext:
            file_type = "document"
            max_size = self.max_doc_size
        else:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if len(content) > max_size:
            raise ValueError(f"文件大小超过限制（{max_size // (1024 * 1024)}MB）")

        session_dir = self.upload_dir / str(user_id) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        file_path = session_dir / safe_name
        file_path.write_bytes(content)

        return UploadResponse(
            url=f"/api/v1/ai/chat/uploads/{user_id}/{session_id}/{safe_name}",
            file_type=file_type,
            original_name=filename,
            size_bytes=len(content),
        ).model_dump()

    def resolve_user_file(
        self,
        *,
        current_user_id: int,
        owner_id: int,
        session_id: str,
        filename: str,
    ) -> Path:
        if owner_id != current_user_id:
            raise PermissionError("无权访问该文件")
        if Path(filename).name != filename:
            raise ValueError("非法文件名")
        session_dir = (self.upload_dir / str(owner_id) / session_id).resolve()
        file_path = (session_dir / filename).resolve()
        if not str(file_path).startswith(str(session_dir)):
            raise ValueError("非法文件路径")
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError("文件不存在")
        return file_path


local_file_store = LocalFileStore()
