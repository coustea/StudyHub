from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(UTC)
