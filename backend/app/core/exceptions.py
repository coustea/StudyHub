from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """应用业务异常基类，统一映射为结构化 HTTP 错误响应。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "bad_request"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConflictError(AppError):
    """资源冲突异常（如用户名或邮箱已存在）。"""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class AuthenticationError(AppError):
    """身份认证失败异常（未登录、凭据错误或令牌失效）。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class NotFoundError(AppError):
    """目标资源不存在或当前用户无权访问异常。"""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册统一的业务异常处理器。"""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.error_code},
            headers=headers,
        )
