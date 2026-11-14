from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.exceptions import AuthenticationError
from app.core.security import decode_token

_EXEMPT_PATHS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}


class JWTAuthMiddleware:
    """纯 ASGI JWT 鉴权中间件，在进入受保护路由前校验 Bearer 令牌。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    async def _send_unauthorized(
        scope: Scope, receive: Receive, send: Send, detail: str
    ) -> None:
        """向客户端返回标准的 401 未认证 JSON 响应。"""
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": detail, "code": "unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """拦截 HTTP 请求，校验 Bearer JWT 并将用户信息写入请求状态。"""
        is_exempt = (
            scope["type"] != "http"
            or scope.get("method", "").upper() == "OPTIONS"
            or scope.get("path", "") in _EXEMPT_PATHS
        )
        if is_exempt:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth_header = headers.get("authorization")
        if not auth_header:
            await self._send_unauthorized(scope, receive, send, "未提供认证凭据。")
            return

        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await self._send_unauthorized(scope, receive, send, "认证请求头格式无效。")
            return

        try:
            user_id, username = decode_token(token.strip(), expected_type="access")
        except AuthenticationError as exc:
            await self._send_unauthorized(scope, receive, send, exc.detail)
            return

        # 注入到 ASGI scope["state"]，供后续接口直接通过 request.state 读取
        state: dict[str, Any] = scope.setdefault("state", {})
        state["user_id"] = user_id
        state["username"] = username

        await self.app(scope, receive, send)
