"""Chat 模块工具函数。

从 agent.py 中提取的辅助函数，包括：文本处理、消息构建、路由判断、状态管理等。
核心业务逻辑（图节点、规划、上下文构建）保留在 agent.py 中。
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from app.infra.logging import get_logger
from app.shared.json_utils import parse_first_json_object

logger = get_logger(__name__)

# 搜索/抓取类工具名称集合，用于单独计数
SEARCH_FETCH_TOOL_NAMES = {
    "duckduckgo_search",
    "web_fetch",
}


# ---------------------------------------------------------------------------
# Prompt 加载
# ---------------------------------------------------------------------------

def load_prompts(agent_dir: Path) -> dict[str, str]:
    """从 prompt.md 读取提示词，按 ## 标题拆分为 classifier / direct_system / tool_system 三个区段。"""
    prompt_path = agent_dir / "prompt.md"
    content = prompt_path.read_text(encoding="utf-8")
    sections: dict[str, str] = {"classifier": "", "direct_system": "", "tool_system": ""}
    current = None
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## classifier"):
            current = "classifier"
            continue
        if stripped.startswith("## direct_system"):
            current = "direct_system"
            continue
        if stripped.startswith("## tool_system"):
            current = "tool_system"
            continue
        if current:
            sections[current] += line + "\n"
    return sections


# ---------------------------------------------------------------------------
# 节点计时
# ---------------------------------------------------------------------------

@contextmanager
def node_timer(node_name: str, **extra: Any) -> Generator[None, None, None]:
    """节点计时上下文管理器，记录每个 StateGraph 节点的进入/退出时间和耗时。"""
    extra_str = " ".join(f"{k}={v}" for k, v in extra.items())
    logger.debug("[TutorAgent] 节点进入 %s %s", node_name, extra_str)
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.debug("[TutorAgent] 节点退出 %s 耗时%dms", node_name, elapsed)


# ---------------------------------------------------------------------------
# 字符串 / 文本处理
# ---------------------------------------------------------------------------

def normalize_message_content(content: Any) -> str:
    """将 LLM 输出统一转为字符串，处理 None 和非字符串类型。"""
    if content is None:
        return ""
    return content if isinstance(content, str) else str(content)


def truncate(value: Any, max_chars: int = 400) -> str:
    """截断任意值到指定字符数，用于日志输出防溢出。非字符串先序列化为 JSON。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def is_unusable_reply_text(text: str) -> bool:
    """检测 LLM 返回的文本是否属于"无效回复"，用于决定是否需要重试。"""
    normalized = (text or "").strip()
    if not normalized:
        return True
    if normalized in {"生成时间：", "生成时间:", "更新时间：", "更新时间:"}:
        return True
    if normalized.startswith("生成时间") and len(normalized) <= 16:
        return True
    if len(normalized) < 8:
        return True
    return False


def looks_like_error_output(text: str) -> bool:
    """检测工具输出文本是否包含错误特征词，用于判断工具调用是否实质性失败。"""
    lower = (text or "").lower()
    markers = [
        "失败", "错误", "error", "exception", "timeout",
        "http 错误", "未知工具", "not found",
    ]
    return any(m in lower for m in markers)


# ---------------------------------------------------------------------------
# 消息构建
# ---------------------------------------------------------------------------

def extract_question(messages: list[AnyMessage]) -> str:
    """从消息列表中提取用户最近的一条纯文本问题，剥离附件标记。"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            return (
                content.split(" [Attached Images:")[0]
                .split(" [Attached Image:")[0]
                .split(" [Attached Files:")[0]
                .strip()
            )
    return ""


def build_messages(system_prompt: str, messages: list[AnyMessage]) -> list[AnyMessage]:
    """将系统提示词拼接到消息列表头部，构建完整的 LLM 输入。"""
    pure = [msg for msg in messages if not isinstance(msg, SystemMessage)]
    return [SystemMessage(content=system_prompt)] + pure


def inject_images(messages: list[AnyMessage], image_urls: Optional[list[str]]) -> list[AnyMessage]:
    """将图片 URL 注入到最后一条 HumanMessage 中，构造多模态消息格式。"""
    if not image_urls:
        return list(messages)
    updated = list(messages)
    for idx in range(len(updated) - 1, -1, -1):
        msg = updated[idx]
        if isinstance(msg, HumanMessage):
            user_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            blocks: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
            for url in image_urls:
                blocks.append({"type": "image_url", "image_url": {"url": url}})
            updated[idx] = HumanMessage(content=blocks)
            break
    return updated


# ---------------------------------------------------------------------------
# 路由判断
# ---------------------------------------------------------------------------

def classify_route(state: dict) -> str:
    """LangGraph 条件路由：根据 classify 节点的结果选择 direct/vision/planner 路径。"""
    return state.get("route", "direct")


def guard_route(state: dict) -> str:
    """LangGraph 条件路由：根据 step_guard 的决策选择下一步节点。"""
    return state.get("last_guard_decision", "final_summarize")


# ---------------------------------------------------------------------------
# SSE 事件
# ---------------------------------------------------------------------------

def stream_event(event: str, data: Any) -> dict[str, Any]:
    """构造 SSE 事件对象，统一事件格式为 {event, data}。"""
    return {"event": event, "data": data}


# ---------------------------------------------------------------------------
# JSON 解析
# ---------------------------------------------------------------------------

def extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    """从 LLM 输出文本中提取第一个 JSON 对象，兼容 code fence 和前后说明文字。"""
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        return parse_first_json_object(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 参数提取
# ---------------------------------------------------------------------------

def extract_query_from_args(args: dict[str, Any]) -> str:
    """从工具调用参数中提取搜索查询关键词，兼容 query/q/keyword/keywords 参数名。"""
    for key in ("query", "q", "keyword", "keywords"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_url_from_args(args: dict[str, Any]) -> str:
    """从工具调用参数中提取 URL。"""
    value = args.get("url")
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# 分类判断
# ---------------------------------------------------------------------------

def is_search_fetch_tool(name: str) -> bool:
    """判断工具是否属于"搜索/抓取"类别，便于单独统计调用情况。"""
    lowered = (name or "").lower()
    if name in SEARCH_FETCH_TOOL_NAMES:
        return True
    if "search" in lowered:
        return True
    if "web_fetch" in lowered or "fetch" in lowered:
        return True
    return False


def likely_requires_lookup(question: str) -> bool:
    """通过关键词判断用户问题是否需要联网检索外部信息。"""
    text = (question or "").strip()
    if not text:
        return False
    markers = ["最新", "今年", "今天", "新闻", "官网", "检索", "搜索", "查一下", "查找", "价格", "数据"]
    return any(m in text for m in markers)


def is_repairable_failure(reason: str, step: dict | None) -> bool:
    """判断步骤失败是否可以通过"修复参数后重试"来恢复。"""
    if not step:
        return False
    text = (reason or "").lower()
    repairable_markers = [
        "参数", "invalid", "超时", "timeout", "empty", "为空",
        "path", "url", "query", "permission",
    ]
    if any(m in text for m in repairable_markers):
        return True
    return str(step.get("kind", "")) in {"tool", "skill"}


# ---------------------------------------------------------------------------
# Budget / 统计
# ---------------------------------------------------------------------------

def make_budget_state() -> dict:
    """创建初始工具调用统计状态：所有计数器归零。"""
    return {
        "total_tool_calls": 0,
        "search_fetch_calls": 0,
    }


def update_budget_after_call(budget_state: dict | None, tool_name: str) -> dict:
    """更新工具调用统计：总调用数 +1，搜索/抓取类单独 +1。"""
    budget = dict(budget_state or make_budget_state())
    budget["total_tool_calls"] = int(budget.get("total_tool_calls", 0)) + 1
    if is_search_fetch_tool(tool_name):
        budget["search_fetch_calls"] = int(budget.get("search_fetch_calls", 0)) + 1
    return budget


# ---------------------------------------------------------------------------
# 结果格式化
# ---------------------------------------------------------------------------

def summarize_step_results(step_results: list[dict], max_items: int = 10) -> str:
    """将步骤执行结果列表格式化为可读的文本摘要，供 LLM 消费。"""
    if not step_results:
        return "暂无步骤结果。"
    chunks: list[str] = []
    for item in step_results[-max_items:]:
        chunks.append(
            f"- step#{item.get('step_index')} {item.get('step_name')} "
            f"success={item.get('success')} summary={truncate(item.get('output_summary', ''))}"
        )
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# 运行时状态合并
# ---------------------------------------------------------------------------

def merge_runtime_state(runtime_state: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """合并节点输出到运行时状态。messages 列表使用追加合并，其余字段直接覆盖。"""
    merged = dict(runtime_state)
    for key, value in output.items():
        if key == "messages" and isinstance(value, list):
            merged[key] = list(merged.get(key, [])) + value
            continue
        merged[key] = value
    return merged