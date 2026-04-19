"""跨模块请求上下文：通过 ContextVar 在异步调用链中传递 user_id / session_id。

供 chat、avatar、profile、tools 等模块共享，
工具层无需显式传递用户身份即可获取当前调用者。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
_current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


@contextmanager
def runtime_context(user_id: int, session_id: str | None = None) -> Iterator[None]:
    """上下文管理器：在 with 块内设置当前 user_id/session_id，退出时自动恢复。"""
    user_token: Token[int | None] = _current_user_id.set(user_id)
    session_token: Token[str | None] = _current_session_id.set(session_id)
    try:
        yield
    finally:
        _current_user_id.reset(user_token)
        _current_session_id.reset(session_token)


def get_current_user_id() -> int | None:
    return _current_user_id.get()


def get_current_session_id() -> str | None:
    return _current_session_id.get()


def set_user_id(user_id: int | None) -> None:
    _current_user_id.set(user_id)


def set_session_id(session_id: str | None) -> None:
    _current_session_id.set(session_id)