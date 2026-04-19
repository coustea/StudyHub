"""集中日志配置模块（Loguru 版本，异步写入）。

兼容性目标：
- 代码侧仍然可以继续使用 `logger = get_logger(__name__)` 与 logging 风格的 `%s` 占位符
- 底层输出统一由 Loguru 负责（文件 + 控制台），并启用 `enqueue=True` 异步写入
- 捕获 `logging` 标准库日志、uvicorn/fastapi/sqlalchemy 等第三方日志，统一导入 Loguru
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

from loguru import logger as _loguru_logger

from app.config import LOG_LEVEL
from app.shared.paths import LOGS_DIR as LOG_DIR


# 输出格式尽量与旧 logging 版保持一致，便于 grep/排障。
_LOGURU_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[logger_name]} | {message}"


class _InterceptHandler(logging.Handler):
    """把标准 logging.Record 转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _loguru_logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        # record.getMessage() 已经完成了 %-style 格式化
        msg = record.getMessage()

        # 让 loguru 的 caller 定位尽量指向“真实调用点”，而不是 logging 框架内部。
        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.bind(logger_name=record.name).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, msg)


class LoguruLoggerProxy:
    """项目内统一 logger 对象。

    目标：不用改全项目日志调用代码，就能把输出切到 Loguru，并启用异步写入。
    同时支持两种常见写法：
    - logging 风格：logger.info("x=%s", x)
    - loguru 风格： logger.info("x={}", x)
    """

    def __init__(self, name: str):
        self._name = name
        self._logger = _loguru_logger.bind(logger_name=name)

    def bind(self, **kwargs: Any) -> "LoguruLoggerProxy":
        proxy = LoguruLoggerProxy(self._name)
        proxy._logger = self._logger.bind(**kwargs)  # type: ignore[attr-defined]
        return proxy

    def _format_message(self, message: Any, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        if not args:
            return (str(message), ())

        if not isinstance(message, str):
            return (str(message), ())

        # 优先保留 loguru 的 {} 格式化能力
        if "{" in message and "}" in message:
            return (message, args)

        # 兼容 logging 的 %-style 格式化
        try:
            return (message % args, ())
        except Exception:
            # 兜底：不让日志调用因为格式问题崩掉
            return (f"{message} args={args!r}", ())

    def _log(self, level: str, message: Any, *args: Any, **kwargs: Any) -> None:
        exc_info = kwargs.pop("exc_info", None)
        msg, fmt_args = self._format_message(message, args)

        l = self._logger
        if exc_info:
            if exc_info is True:
                l = l.opt(exception=True)
            else:
                l = l.opt(exception=exc_info)
        l.log(level, msg, *fmt_args, **kwargs)

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._log("DEBUG", message, *args, **kwargs)

    def info(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._log("INFO", message, *args, **kwargs)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._log("WARNING", message, *args, **kwargs)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._log("ERROR", message, *args, **kwargs)

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> None:
        # 与 logging 行为一致：记录当前异常堆栈（需要在 except 块内调用）
        msg, fmt_args = self._format_message(message, args)
        self._logger.opt(exception=True).error(msg, *fmt_args, **kwargs)

    def critical(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._log("CRITICAL", message, *args, **kwargs)


def get_logger(name: str) -> LoguruLoggerProxy:
    """获取项目 logger（不再返回标准库 logging.Logger）。"""
    return LoguruLoggerProxy(name)


def get_loguru_logger(name: str):
    """可选：直接拿 loguru logger（新代码可用），带上 logger_name。"""
    return _loguru_logger.bind(logger_name=name)


def _parse_level(raw: str) -> str:
    value = (raw or "").strip().upper()
    return value if value in {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"

_CONFIGURED = False


def setup_logging(*, level: Optional[str] = None, force: bool = False) -> None:
    """初始化 Loguru + 标准库 logging 拦截。

    在应用启动时调用一次即可（FastAPI lifespan）。
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_level = _parse_level(level or LOG_LEVEL)

    # 1) 配置 loguru sinks（enqueue=True 异步写入）
    _loguru_logger.remove()
    _loguru_logger.configure(extra={"logger_name": "root"})

    # 控制台
    _loguru_logger.add(
        sys.stdout,
        level=log_level,
        format=_LOGURU_FORMAT,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    # 全量日志：按天轮转，保留 30 天
    _loguru_logger.add(
        str(LOG_DIR / "app.log"),
        level=log_level,
        format=_LOGURU_FORMAT,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    # 错误日志：按大小轮转，最多 10 份
    _loguru_logger.add(
        str(LOG_DIR / "error.log"),
        level="ERROR",
        format=_LOGURU_FORMAT,
        rotation="10 MB",
        retention=10,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    # 2) 拦截标准 logging：所有旧代码 logger.info("x=%s", x) 都会被转发到 loguru
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # 清理常见第三方 logger 的 handler，避免重复输出
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.engine",
        "aiomysql",
    ):
        ext_logger = logging.getLogger(name)
        ext_logger.handlers.clear()
        ext_logger.propagate = True

    _loguru_logger.bind(logger_name="root").info(
        "[Logging] 日志系统初始化完成: log_dir={log_dir} level={level} async_enqueue={enqueue}",
        log_dir=str(LOG_DIR),
        level=log_level,
        enqueue=True,
    )

    _CONFIGURED = True
