"""
网页抓取工具。

提供 web_fetch 工具，供 LLM 抓取搜索引擎或任意网页内容。
返回清洗后的纯文本（去除 HTML 标签），限制最大长度以保护上下文窗口。
"""

from __future__ import annotations

import re
from typing import Optional

import httpx
from langchain.tools import tool

from app.infra.logging import get_logger
from app.tools.registry import register

logger = get_logger(__name__)

# HTML 标签剥离正则
_TAG_RE = re.compile(r"<[^>]+>")
# 连续空白压缩
_WS_RE = re.compile(r"\s+")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@tool("web_fetch")
def web_fetch(
    url: str,
    *,
    max_length: Optional[int] = 8000,
) -> str:
    """抓取指定 URL 的网页内容，返回清洗后的纯文本。

    用于搜索引擎查询、网页内容获取等场景。
    搜索引擎 URL 示例:
      - 百度: https://www.baidu.com/s?wd=关键词
      - Bing: https://cn.bing.com/search?q=关键词
      - Google: https://www.google.com/search?q=关键词
      - DuckDuckGo: https://duckduckgo.com/html/?q=关键词

    Args:
        url: 要抓取的网页 URL
        max_length: 返回文本的最大字符数，默认 8000
    """
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=15.0,
            headers=_DEFAULT_HEADERS,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        encoding = resp.charset_encoding or "utf-8"
        raw_text = resp.content.decode(encoding, errors="replace")

        # 去除 HTML 标签，保留纯文本
        text = _TAG_RE.sub(" ", raw_text)
        text = _WS_RE.sub(" ", text).strip()

        # 截断
        if max_length and len(text) > max_length:
            text = text[:max_length] + f"\n\n... (已截断，原文共 {len(text)} 字符)"

        logger.info(
            "[web_fetch] url=%s status=%d len=%d",
            url, resp.status_code, len(text),
        )
        return text

    except httpx.HTTPStatusError as e:
        logger.warning("[web_fetch] HTTP error: url=%s status=%d", url, e.response.status_code)
        return f"HTTP 错误 {e.response.status_code}: {e.response.reason_phrase}"
    except httpx.TimeoutException:
        logger.warning("[web_fetch] timeout: url=%s", url)
        return f"请求超时: {url}"
    except Exception as e:
        logger.error("[web_fetch] failed: url=%s error=%s", url, e)
        return f"抓取失败: {e}"


register(web_fetch)
