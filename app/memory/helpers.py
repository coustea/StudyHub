"""共享文本处理工具 — 为 memory 子模块提供文本标准化、时间戳、token 估算等基础能力。"""

from datetime import datetime, timedelta

from app.infra.logging import get_logger

logger = get_logger(__name__)


def normalize_text(content: str) -> str:
    """文本标准化：去除首尾空白、统一小写、压缩连续空格为单个空格，用于去重比较。"""
    return " ".join((content or "").strip().lower().split())


def now() -> datetime:
    """返回当前本地时间（无时区），作为全模块统一的时间获取入口。"""
    return datetime.now()


def message_expire_cutoff(days: int = 7) -> datetime:
    """计算消息过期截止时间点：当前时间减去指定天数，早于此时间的消息视为已过期。"""
    cutoff = now() - timedelta(days=max(days, 0))
    logger.debug("[Helpers] 消息过期截止时间: days=%d, cutoff=%s", days, cutoff.isoformat())
    return cutoff


def estimate_token_count(text: str) -> int:
    """估算文本的 token 数量（粗粒度）：取字符数/4 和英文单词数的最大值。
    对于中文文本，字符数/4 更接近实际 token 数；对于英文文本，单词数更接近。"""
    stripped = (text or "").strip()
    if not stripped:
        return 0
    by_chars = max(1, len(stripped) // 4)  # 中文约 1 token ≈ 1.5~2 字符，保守取 4
    by_words = len(stripped.split())  # 英文按空格分词计数
    estimated = max(by_chars, by_words)
    logger.debug("[Helpers] token 估算: len=%d, by_chars=%d, by_words=%d, result=%d",
                 len(stripped), by_chars, by_words, estimated)
    return estimated