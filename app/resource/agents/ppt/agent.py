"""
PPT 演示文稿生成 Agent（骨架）。
基于 BaseResourceAgent 实现，通过本地工具生成结构化 PPT 文件。
"""

import json
import re
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, ToolMessage

from app.infra.logging import get_logger
from app.resource.base_agent import BaseResourceAgent, BaseAgentState
from app.tools.file_operator import save_ppt_file

logger = get_logger(__name__)


class PptState(BaseAgentState):
    """PPT 生成的专属状态字段"""
    # PPT 特有的输出字段
    slide_count: int
    outline: str
    outline_markdown: str
    speaker_notes: str
    file_path: Optional[str]
    slide_titles: list[str]
    style: str


_MARKDOWN_FENCE_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"^#\s+.+$", re.MULTILINE)
_SLIDE_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_NOTE_RE = re.compile(r"^\[note\]\s*$", re.MULTILINE)
_VISUAL_KEYWORDS = ("视觉", "图解", "图像", "示意", "案例驱动")
_SEQUENTIAL_KEYWORDS = ("顺序", "逻辑", "步骤", "推理", "序列")
_GLOBAL_KEYWORDS = ("整体", "全局", "宏观", "综合", "框架")


def _select_ppt_style(cognitive_style: str | None) -> str:
    """根据认知风格选择更贴近学习体验的视觉主题。"""
    style = (cognitive_style or "").strip()
    if any(keyword in style for keyword in _VISUAL_KEYWORDS):
        return "creative_bold"
    if any(keyword in style for keyword in _SEQUENTIAL_KEYWORDS):
        return "corporate_blue"
    if any(keyword in style for keyword in _GLOBAL_KEYWORDS):
        return "nature_green"
    return "modern_minimal"


def _extract_outline_markdown(text: str) -> str:
    """从模型最终输出中提取 Markdown 幻灯片大纲。"""
    raw = (text or "").strip()
    if not raw:
        return ""

    match = _MARKDOWN_FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()

    if "# " not in raw or "## " not in raw:
        return ""
    return raw


def _extract_tool_payload(payload: Any) -> dict[str, Any] | None:
    """统一解析 save_ppt_file 的返回载荷。"""
    if isinstance(payload, dict):
        return payload

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "text" in item:
                try:
                    parsed = json.loads(item["text"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return None

    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    return None


def _check_outline_quality(outline_markdown: str) -> tuple[bool, str, int]:
    """对 PPT Markdown 大纲做最低质量门槛校验。"""
    if not outline_markdown.strip():
        return False, "未检测到可用的 PPT Markdown 大纲。", 0
    if not _TITLE_RE.search(outline_markdown):
        return False, "PPT 大纲缺少主标题，请使用一级标题作为整份课件标题。", 0

    slide_count = len(_SLIDE_RE.findall(outline_markdown))
    note_count = len(_NOTE_RE.findall(outline_markdown))

    if slide_count < 6:
        return False, "PPT 页数不足，至少需要 6 页内容页来形成完整教学流程。", slide_count
    if note_count < max(3, slide_count // 2):
        return False, "讲者备注不足，请为更多页面补充 [note] 讲解备注。", slide_count
    return True, "", slide_count


class PptAgent(BaseResourceAgent):
    """PPT 演示文稿生成 Agent。"""

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "list_directory", "file_tree", "find_files", "get_file_info",
        "save_ppt_file",
    ]
    skill_names = ["ppt-generation", "ppt-visual", "pptx"]

    def __init__(self) -> None:
        super().__init__(
            name="PptAgent",
            agent_dir=Path(__file__).parent,
            state_schema=PptState,
            temperature=0.3,
        )

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        """黑板记忆：从前置 Agent 输出中提取关键上下文"""
        ctx = ""
        if "content" in shared_memory:
            content_data = shared_memory["content"]
            outline = content_data.get("outline", "")
            if outline:
                ctx += f"【参考内容大纲】\n{outline}\n"
        if "mindmap" in shared_memory:
            mindmap_data = shared_memory["mindmap"]
            file_path = mindmap_data.get("file_path", "")
            if file_path:
                ctx += f"【知识拓扑图】\n已生成思维导图: {file_path}\n"
        return ctx

    def _format_user_profile(self, profile: dict[str, Any]) -> str:
        # 当前 PPT 个性化主要围绕认知风格展开，后续可以继续扩展。
        if not profile: return ""
        parts = []
        if profile.get("cognitive_style"):
            parts.append(f"- 认知风格: {profile['cognitive_style']}")
        return "\n".join(parts)

    def _build_system_message(self, state: Any) -> str:
        user_profile = state.get("user_profile", {})
        system_prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", ""),
            topic=state.get("topic", ""),
            gap=state.get("gap", ""),
            cognitive_style=user_profile.get("cognitive_style", "通用"),
        )
        system_prompt = self._append_context_to_prompt(system_prompt, state)
        return system_prompt + f"\n\n## [视觉主题建议]\n本次推荐主题样式：{state.get('style', 'corporate_blue')}"

    def _build_initial_human_message(self, state: Any) -> str:
        topic = state.get("topic", "")
        # 当前版本只保留本地工具保存路径，避免外部第三方能力影响流程稳定性。
        return (
            f"请为主题 '{topic}' 生成一份 PPT 演示文稿，并在大纲完成后调用 save_ppt_file 保存。"
            f" 推荐视觉主题为 {state.get('style', 'corporate_blue')}。"
        )

    async def _validate_node(self, state: Any) -> dict:
        """校验节点：提取本地工具返回的文件路径。"""
        messages = state.get("messages", [])
        content = ""
        file_path = None
        slide_count = 0
        slide_titles: list[str] = []

        if messages and isinstance(messages[-1], AIMessage):
            content = messages[-1].content.strip()

        outline_markdown = _extract_outline_markdown(content)
        quality_ok, quality_feedback, inferred_slide_count = _check_outline_quality(outline_markdown)

        for msg in messages:
            if not isinstance(msg, ToolMessage) or msg.name != "save_ppt_file":
                continue

            payload = msg.content
            data = _extract_tool_payload(payload)
            if isinstance(data, dict):
                file_path = data.get("file_path") or data.get("filePath")
                slide_count = int(data.get("slide_count", 0) or 0)
                slide_titles = list(data.get("slide_titles", []) or [])
                break

        if not file_path and content:
            # 再兜底从模型文本里抠一次 file_path，避免工具返回格式稍有变化就全盘失败。
            path_match = re.search(r'file_path[：:]\s*(.+?)(?:\n|$)', content)
            if path_match:
                file_path = path_match.group(1).strip()

        if not file_path and outline_markdown:
            if quality_ok:
                logger.info("[PptAgent] 未检测到工具结果，尝试根据 Markdown 大纲自动保存 PPT")
                try:
                    payload = save_ppt_file.invoke(
                        {
                            "topic": state.get("topic", "教学演示"),
                            "outline_markdown": outline_markdown,
                            "style": state.get("style", "corporate_blue"),
                        }
                    )
                    data = _extract_tool_payload(payload) or {}
                    file_path = data.get("file_path") or data.get("filePath")
                    slide_count = int(data.get("slide_count", 0) or 0)
                    slide_titles = list(data.get("slide_titles", []) or [])
                except Exception as exc:
                    logger.error("[PptAgent] 自动保存 PPT 失败: %s", exc, exc_info=exc)
                    return {
                        "is_valid": False,
                        "validation_feedback": f"PPT 大纲已生成，但保存 PPT 失败：{exc}",
                        "file_path": None,
                        "slide_count": inferred_slide_count,
                        "slide_titles": [],
                        "outline_markdown": outline_markdown,
                    }
            else:
                logger.warning("[PptAgent] PPT 大纲质量不足: %s", quality_feedback)

        logger.info(f"[PptAgent] 校验 PPT 内容，文件路径: {file_path}")
        is_valid = bool(file_path)

        # 构造校验反馈
        if is_valid:
            feedback = ""
        else:
            feedback = (
                "未检测到 PPT 文件路径。"
                "请调用 save_ppt_file 工具生成并保存 PPT。"
            )

        return {
            "is_valid": is_valid,
            "validation_feedback": feedback if is_valid else quality_feedback or feedback,
            "file_path": file_path,
            "slide_count": slide_count or inferred_slide_count,
            "slide_titles": slide_titles,
            "outline_markdown": outline_markdown,
        }

    async def generate_ppt(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[PptAgent] 收到生成请求: topic={topic}")
        await self._ensure_graph()
        resolved_style = _select_ppt_style((user_profile or {}).get("cognitive_style"))

        # PPT 阶段依赖前面多个 Agent 的产物，所以状态里要保留 shared_memory。
        initial_state: PptState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "outline_markdown": "",
            "slide_titles": [],
            "style": resolved_style,
            "is_valid": False,
            "validation_feedback": "",
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
        }

        try:
            logger.info("[PptAgent] 开始执行 PPT 工作流: tool=save_ppt_file")
            result = await self.graph.ainvoke(initial_state, {"recursion_limit": 15})
            logger.info(
                "[PptAgent] PPT 工作流完成: is_valid=%s file_path=%s slide_count=%s",
                result.get("is_valid"),
                result.get("file_path"),
                result.get("slide_count"),
            )
        except Exception as e:
            logger.error(f"[PptAgent] 工作流执行失败: {e}")
            return {
                "success": False,
                "content": "",
                "file_path": None,
                "slide_count": 0,
                "outline": "",
                "speaker_notes": "",
                "error": str(e)
            }

        messages = result.get("messages", [])
        final_content = messages[-1].content if messages else ""

        # 提取校验节点设置的文件路径
        file_path = result.get("file_path")
        # 这里把 final_content 同时当作 outline 的兜底来源，避免只存文件路径没有文本上下文。

        return {
            "success": bool(file_path),
            "content": final_content,
            "file_path": file_path,
            "slide_count": result.get("slide_count", final_content.count("##") if final_content else 0),
            "outline": result.get("outline_markdown") or final_content,
            "outline_markdown": result.get("outline_markdown") or final_content,
            "slide_titles": result.get("slide_titles", []),
            "style": resolved_style,
            "speaker_notes": "",
            "error": result.get("error") if file_path else result.get("error"),
        }


if __name__ == '__main__':
    import asyncio

    agent = PptAgent()

    async def main():
        await agent._ensure_graph()

        result = await agent.generate_ppt(
            topic="操作系统进程管理",
            course="操作系统",
            major="计算机科学",
            gap="对进程调度算法理解不清晰",
            user_profile={
                "cognitive_style": "偏逻辑推理"
            },
            shared_memory={
                "content": {
                    "outline": "进程定义、PCB、调度算法（FCFS、SJF、RR）、同步与互斥"
                },
                "mindmap": {
                    "file_path": "/tmp/mindmap.png"
                }
            }
        )

        print("=" * 50)
        print("[PPT 生成结果]")
        print("=" * 50)

        print(f"success: {result['success']}")
        print(f"file_path: {result['file_path']}")
        print(f"slide_count: {result['slide_count']}")

        print("\n[PPT 内容]\n")
        print(result["content"])

        if result.get("error"):
            print("\n[错误信息]")
            print(result["error"])

    asyncio.run(main())
