"""DuckDuckGo 搜索工具封装。

通过 langchain_community.tools.DuckDuckGoSearchRun 接入统一工具注册表。
"""

from __future__ import annotations

from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool

from app.infra.logging import get_logger
from app.tools.registry import register

logger = get_logger(__name__)


@tool("duckduckgo_search")
def duckduckgo_search(query: str) -> str:
    """使用 DuckDuckGo 搜索网页，返回文本结果摘要。"""
    try:
        search_tool = DuckDuckGoSearchRun()
        result = search_tool.run(query)
        logger.info(
            "[duckduckgo_search] query=%r result_preview=%r",
            query,
            str(result)[:300],
        )
        return str(result)
    except Exception as exc:
        logger.warning("[duckduckgo_search] failed: query=%r error=%s", query, exc)
        return f"DuckDuckGo 搜索失败: {exc}"


register(duckduckgo_search)
