"""
思维导图生成 Agent。
使用本地工具生成 HTML 思维导图文件。
"""

import os
import re
import json
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, ToolMessage

from app.infra.llm import get_spark_x_llm
from app.infra.logging import get_logger
from app.resource.base_agent import BaseResourceAgent, BaseAgentState
from app.tools.markdown_to_mindmap import markdown_to_mindmap

logger = get_logger(__name__)


class MindmapState(BaseAgentState):
    need: str
    extra: str
    file_path: Optional[str]
    html_content: Optional[str]
    agent_output: Optional[str]
    markdown_content: Optional[str]
    node_count: int


NEED_MAP = {
    "exam": "考前突击 (侧重考点与易错题)",
    "review": "课后复习 (侧重知识梳理与图解)",
    "deep": "深度探究 (侧重底层原理与拓展)",
    "practice": "实践应用 (侧重代码或实操案例)",
}

_MARKDOWN_FENCE_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_ROOT_RE = re.compile(r"^#\s+.+$", re.MULTILINE)
_TOP_LEVEL_BRANCH_RE = re.compile(r"^-\s+.+$", re.MULTILINE)
_NESTED_BRANCH_RE = re.compile(r"^\s+-\s+.+$", re.MULTILINE)


def _extract_markdown_content(text: str) -> str:
    """从模型输出中提取 Markdown 思维导图源码。"""
    raw = (text or "").strip()
    if not raw:
        return ""

    match = _MARKDOWN_FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()

    if "# " not in raw or "- " not in raw:
        return ""
    return raw


def _count_mindmap_nodes(markdown_text: str) -> int:
    """统计导图节点数量，根节点也计入总数。"""
    if not markdown_text.strip():
        return 0
    lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]
    return sum(1 for line in lines if line.startswith("# ") or line.startswith("- "))


def _count_top_level_branches(markdown_text: str) -> int:
    """统计一级分支数量，用来判断导图是否足够展开。"""
    return len(_TOP_LEVEL_BRANCH_RE.findall(markdown_text))


def _check_markdown_quality(markdown_text: str) -> tuple[bool, str, int]:
    """对模型产出的 Markdown 导图做最小质量校验。"""
    node_count = _count_mindmap_nodes(markdown_text)
    if not markdown_text:
        return False, "未检测到可用的 Markdown 思维导图内容。", node_count
    if not _ROOT_RE.search(markdown_text):
        return False, "导图缺少根节点标题，请以一级标题作为主题根节点。", node_count
    if _count_top_level_branches(markdown_text) < 3:
        return False, "导图结构过于单薄，一级分支至少需要 3 个。", node_count
    if len(_NESTED_BRANCH_RE.findall(markdown_text)) < 4:
        return False, "导图展开深度不足，请补充更多二级或三级节点。", node_count
    if node_count < 8:
        return False, "导图结构过于稀疏，请补充更多关键知识节点。", node_count
    return True, "", node_count


def _extract_file_path_from_tool_payload(content: Any) -> str | None:
    """从工具返回载荷中提取导图 HTML 文件路径。"""
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and "text" in item:
                try:
                    inner = json.loads(item["text"]) if isinstance(item["text"], str) else item["text"]
                except (json.JSONDecodeError, TypeError):
                    continue
                file_path = _extract_file_path_from_tool_payload(inner)
                if file_path:
                    return file_path
        return None

    if isinstance(content, dict):
        return content.get("file_path") or content.get("filePath")

    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"(/.*\.html)", content)
            return match.group(1) if match else None
        return _extract_file_path_from_tool_payload(parsed)

    return None


class MindmapGenerator(BaseResourceAgent):
    """思维导图生成 Agent。

    使用本地工具将 Markdown 转换为交互式 HTML 思维导图。
    """

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "list_directory", "file_tree", "find_files", "get_file_info",
        "markdown_to_mindmap",
    ]
    def __init__(self) -> None:
        super().__init__(
            name="MindmapAgent",
            agent_dir=Path(__file__).parent,
            state_schema=MindmapState,
            temperature=0.1,
        )
        self.llm = get_spark_x_llm(temperature=0.1)

    def _build_system_message(self, state: Any) -> str:
        need_key = state.get("need", "review")
        need_text = NEED_MAP.get(need_key, need_key)

        prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", "待定"),
            topic=state.get("topic", "未知知识点"),
            gap=state.get("gap", "无"),
            need=need_text,
            extra=state.get("extra", "无"),
        )

        prompt += (
            "\n\n【执行指南】\n"
            "1. 先设计 Markdown 思维导图结构。\n"
            "2. 使用 `markdown_to_mindmap` 工具生成 HTML 思维导图。\n"
            "3. 生成成功后，向用户反馈生成的 HTML 文件路径即可。\n"
            "注意：不要直接输出 Markdown 源码，必须调用工具生成 HTML。"
        )

        return self._append_context_to_prompt(prompt, state)

    def _build_initial_human_message(self, state: Any) -> str:
        topic = state.get('topic')
        gap = state.get('gap')
        need = state.get("need", "review")
        extra = state.get("extra", "")

        msg = f"请为知识点 '{topic}' 生成思维导图。"
        if gap and gap != "无":
            msg += f" 特别注意学生在 '{gap}' 方面存在薄弱环节，请在图中重点体现。"
        if need:
            msg += f" 本次导图目标为：{need}。"
        if extra:
            msg += f" 额外要求：{extra}。"
        msg += " 请完成 Markdown 结构设计后立即调用 markdown_to_mindmap 生成 HTML。"
        return msg

    async def _validate_node(self, state: Any) -> dict:
        """从工具调用结果中提取 file_path 和 html_content。"""
        messages = state.get("messages", [])
        file_path = None
        html_content = None

        # 获取最后的 AI 消息作为 agent_output
        agent_output = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                agent_output = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        markdown_content = _extract_markdown_content(agent_output)
        quality_ok, quality_feedback, node_count = _check_markdown_quality(markdown_content)

        # 从 ToolMessage 中提取 markmap 工具返回的文件路径
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.name == "markdown_to_mindmap":
                file_path = _extract_file_path_from_tool_payload(msg.content)
                if file_path:
                    break

        if not file_path and markdown_content:
            if quality_ok:
                logger.info("[MindmapAgent] 未检测到工具结果，尝试用 Markdown 自动补生成 HTML")
                try:
                    tool_result = markdown_to_mindmap.invoke({"markdown_text": markdown_content})
                    file_path = _extract_file_path_from_tool_payload(tool_result)
                except Exception as exc:
                    logger.error("[MindmapAgent] 自动补生成 HTML 失败: %s", exc, exc_info=exc)
                    return {
                        "file_path": None,
                        "html_content": None,
                        "agent_output": agent_output,
                        "markdown_content": markdown_content,
                        "node_count": node_count,
                        "is_valid": False,
                        "retry_count": state.get("retry_count", 0) + 1,
                        "validation_feedback": f"导图 Markdown 已生成，但转换 HTML 失败：{exc}",
                    }
            else:
                logger.warning("[MindmapAgent] Markdown 导图质量不足: %s", quality_feedback)

        # 读取 HTML 内容
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
            except Exception as e:
                logger.warning(f"[MindmapAgent] 无法读取 HTML 文件 {file_path}: {e}")

        is_valid = bool(file_path)
        retry_count = state.get("retry_count", 0) + 1

        if not is_valid:
            logger.warning(
                f"[MindmapAgent] 校验未通过 (retry={retry_count}): "
                f"未找到 file_path，已有 {len(messages)} 条消息"
            )

        return {
            "file_path": file_path,
            "html_content": html_content,
            "agent_output": agent_output,
            "markdown_content": markdown_content,
            "node_count": node_count,
            "is_valid": is_valid,
            "retry_count": retry_count,
            "validation_feedback": "" if is_valid else quality_feedback or "未检测到思维导图文件路径。请确保调用了 markdown_to_mindmap 工具并正确生成了 HTML 文件。",
        }

    async def generate_mindmap(
        self,
        topic: str = "",
        gap: str = "",
        course: str = "",
        major: str = "通用",
        need: str = "review",
        extra: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[MindmapAgent] 收到生成请求: topic={topic}, gap={gap}")
        await self._ensure_graph()

        # 思维导图是首阶段资源，所以这里不依赖其他 Agent，只吃用户请求和画像。
        initial_state: MindmapState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "need": need,
            "extra": extra,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "file_path": None,
            "html_content": None,
            "agent_output": None,
            "markdown_content": None,
            "node_count": 0,
            "is_valid": False,
            "validation_feedback": "",
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
        }

        try:
            logger.info("[MindmapAgent] 开始执行导图工作流: need=%s extra=%r", need, extra)
            result = await self.graph.ainvoke(initial_state, {"recursion_limit": 25})
            logger.info(
                "[MindmapAgent] 导图工作流完成: is_valid=%s file_path=%s",
                result.get("is_valid"),
                result.get("file_path"),
            )
        except Exception as e:
            logger.error(f"[MindmapAgent] 工作流执行失败: {e}")
            return {"success": False, "file_path": None, "html_content": None, "agent_output": "", "error": str(e)}

        return {
            "success": result.get("is_valid", False),
            "file_path": result.get("file_path"),
            "html_content": result.get("html_content"),
            "agent_output": result.get("agent_output", ""),
            "markdown_content": result.get("markdown_content", ""),
            "node_count": result.get("node_count", 0),
            "error": result.get("error") if not result.get("is_valid") else None,
        }

if __name__ == '__main__':
    import asyncio

    _gen = MindmapGenerator()
    result = asyncio.run(
        _gen.generate_mindmap(
            topic="Python 面向对象编程",
            gap="类与继承的理解",
            course="Python程序设计",
            major="计算机科学",
            need="review",
            extra="请包含 UML 类图示例",
        )
    )

    if result["success"]:
        print(f"思维导图生成成功: {result['file_path']}")
    else:
        print(f"生成失败: {result.get('error', '未知错误')}")
