"""
工具注册表。

每个工具文件在模块级别调用 register() 将自己注册到全局字典中。
Agent 通过 tool_names 列表声明依赖，运行时调用 get_many() 解析。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.infra.logging import get_logger

logger = get_logger(__name__)

_registry: dict[str, BaseTool] = {}


def register(tool: BaseTool) -> None:
    """将工具注册到全局字典。同名工具后注册的会覆盖先注册的。"""
    if tool.name in _registry:
        logger.warning("[ToolRegistry] 工具 %s 被重复注册，后者覆盖前者", tool.name)
    _registry[tool.name] = tool


def get(name: str) -> BaseTool:
    """按名字获取工具，找不到抛 KeyError。"""
    if name not in _registry:
        raise KeyError(f"工具 '{name}' 未注册。可用工具: {sorted(_registry.keys())}")
    return _registry[name]


def get_many(names: list[str]) -> list[BaseTool]:
    """按名字列表批量获取工具。"""
    return [get(name) for name in names]


def available() -> list[str]:
    """返回所有已注册工具的名字列表（排序）。"""
    return sorted(_registry.keys())
