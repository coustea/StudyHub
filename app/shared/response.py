from typing import Any

from pydantic import BaseModel


class HttpResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None

    @staticmethod
    def success(data: Any = None, message: str = "success") -> "HttpResponse":
        return HttpResponse(code=200, message=message, data=data)

    @staticmethod
    def error(code: int = 500, message: str = "error", data: Any = None) -> "HttpResponse":
        return HttpResponse(code=code, message=message, data=data)
