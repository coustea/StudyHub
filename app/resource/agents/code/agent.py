"""
代码实操案例生成 Agent。
基于 BaseResourceAgent 实现，并使用黑板模式与用户画像。
"""

import asyncio
import ast
import re
import json
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


from app.infra.logging import get_logger
from app.resource.base_agent import BaseResourceAgent, BaseAgentState

logger = get_logger(__name__)


class CodeState(BaseAgentState):
    code_content: str
    detected_language: str
    explained_content: str


_LANG_KEYWORDS: dict[str, list[str]] = {
    "python": ["python", "python3", "py"],
    "javascript": ["javascript", "js", "node", "nodejs"],
    "java": ["java"],
    "c": ["c", "clang"],
    "cpp": ["cpp", "c++", "cxx"],
    "sql": ["sql", "mysql", "postgresql"],
    "go": ["go", "golang"],
    "rust": ["rust", "rs"],
}

_CODE_BLOCK_RE = re.compile(r"```(\w+)\s*\n(.*?)\n```", re.DOTALL)


def _detect_language(code_content: str) -> str:
    # 优先从 Markdown fenced code block 的语言标签识别语言，避免靠内容猜测。
    match = _CODE_BLOCK_RE.search(code_content)
    if match:
        lang_tag = match.group(1).lower()
        for canonical, aliases in _LANG_KEYWORDS.items():
            if lang_tag in aliases:
                return canonical
        return lang_tag
    return "unknown"


def _extract_code_block(code_content: str) -> str:
    # 保存到前端或执行器时，更需要纯代码体，因此这里抽掉 markdown 外壳。
    match = _CODE_BLOCK_RE.search(code_content)
    if match:
        return match.group(2)
    return code_content


class CodeAgent(BaseResourceAgent):
    """代码实操案例生成 Agent。

    最后由 LLM 添加教学注释和逐步解析。

    Attributes:
        name:           "CodeAgent"
        agent_dir:      agents/code/，包含 prompt.md、tools/
        state_schema:   CodeState，包含 code_content/detected_language/explained_content
        method:         generate_code() — 对外入口
        output:         {success, content, file_path, detected_language, code_only, error}

    工作流: agent → tools(safe_shell) → validate(添加教学注释) → end
    DAG 阶段: core（依赖 mindmap）
    黑板记忆: 读取 mindmap.agent_output（知识结构）和 content.outline（内容大纲）
    用户画像: 读取 knowledge_level（知识水平）和 learning_pace（学习节奏）
    """

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "execute_shell", "execute_shell_sync",
        "run_code", "run_file",
        "list_directory", "file_tree", "find_files", "get_file_info",
        "safe_shell",
    ]
    skill_names = []

    def __init__(self) -> None:
        super().__init__(
            name="CodeAgent",
            agent_dir=Path(__file__).parent,
            state_schema=CodeState,
            temperature=0.2,
        )

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        ctx = ""
        # 代码案例通常需要跟知识结构和正文讲解保持一致，因此这里同时读取导图和内容大纲。
        if "mindmap" in shared_memory:
            mm = shared_memory["mindmap"].get("agent_output", "")
            if mm: ctx += f"【思维导图核心结构】\n{mm}\n"
        if "content" in shared_memory:
            outline = shared_memory["content"].get("outline", "")
            if outline: ctx += f"【内容大纲】\n{outline}\n"
        return ctx

    def _format_user_profile(self, profile: dict[str, Any]) -> str:
        # 这里只挑会直接影响代码案例难度和节奏的字段塞进 prompt。
        if not profile: return ""
        parts = []
        if profile.get("knowledge_level"):
            parts.append(f"- 知识水平: {profile['knowledge_level']}")
        if profile.get("learning_pace"):
            parts.append(f"- 学习节奏: {profile['learning_pace']}")
        return "\n".join(parts)

    def _build_system_message(self, state: Any) -> str:
        """构建 System Prompt（返回字符串）。"""
        user_profile = state.get("user_profile", {})
        system_prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", ""),
            topic=state.get("topic", ""),
            gap=state.get("gap", ""),
            knowledge_level=user_profile.get("knowledge_level", "中等"),
            learning_pace=user_profile.get("learning_pace", "中等"),
        )
        # 注入上下文（用户画像、黑板记忆、skills 工具说明）
        system_prompt = self._append_context_to_prompt(system_prompt, state)

        instruction = (
            "\n\n【重要指令】\n"
            "1. 请首先直接生成对应的完整实操代码，并以 Markdown 形式输出。\n"
            "2. 如果你能够稳定调用 `safe_shell` 工具，可以在生成代码后进行一次本地运行验证。\n"
            "3. 如果当前轮次没有调用工具能力，也不要停下来，直接给出完整、可运行、带说明的代码案例。\n"
            "4. 不要只回复计划、说明或向用户追问，必须产出最终代码内容。"
        )
        return system_prompt + instruction

    def _build_initial_human_message(self, state: Any) -> str:
        """构建初次请求的消息（返回字符串）。"""
        return f"请为主题 '{state.get('topic')}' 生成一个完整的可运行代码案例。"

    def _save_to_workplace(self, sub_dir: str, topic: str, content: str, ext: str = "md") -> str:
        from app.tools.file_operator import save_to_workplace
        # 代码案例统一保存成 markdown，便于同时承载代码、说明和运行结果。
        return save_to_workplace(
            sub_dir=sub_dir,
            topic=topic,
            content=content,
            ext=ext,
        )

    def _failure_result(self, state: Any, feedback: str, **fields: Any) -> dict[str, Any]:
        # 校验失败时统一走这个出口，确保 retry_count、error 字段行为一致。
        retry_count = state.get("retry_count", 0) + 1
        result = {
            "is_valid": False,
            "validation_feedback": feedback,
            "retry_count": retry_count,
            **fields,
        }
        if retry_count >= state.get("max_retries", 2):
            result["error"] = feedback
        return result

    async def _validate_node(self, state: Any) -> dict:
        messages = state.get("messages", [])
        code_content = ""
        # 这里只取最后一条真正的 AI 文本输出，避免把工具消息误认为代码正文。
        for message in reversed(messages):
            if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip():
                code_content = message.content.strip()
                break

        if not code_content:
            return self._failure_result(
                state,
                "未生成任何代码内容，请直接输出完整可运行的 Markdown 代码案例，不要只给解释或空响应。",
                code_content="",
                detected_language="unknown",
                explained_content="",
            )

        language = _detect_language(code_content)
        if "```" not in code_content:
            return self._failure_result(
                state,
                "缺少带语言标记的代码块，请按 Markdown 结构输出完整代码案例。",
                code_content=code_content,
                detected_language=language,
                explained_content="",
            )

        logger.info(f"[CodeAgent] _validate_node (add_explanation): 为 {language} 代码添加教学注释")

        explain_messages = [
            HumanMessage(
                content=(
                    "你是一位编程教学专家。请在以下代码案例中添加详细的编号式逐步解析：\n\n"
                    "1. 在代码中的关键行前添加编号行内注释（如 `# [1] 定义数据结构`）\n"
                    "2. 在代码块之前添加 2-3 句的背景说明\n"
                    "3. 在代码块之后添加编号解析列表，解释每一步的含义和设计思路\n\n"
                    f"编程语言：{language}\n\n"
                    f"原始代码：\n{code_content}\n\n"
                    "请输出完整的 Markdown 文档（包含说明 + 带注释的代码 + 解析）。"
                )
            ),
        ]

        try:
            response = await self.llm.ainvoke(explain_messages)
            explained = response.content.strip()
            logger.info(f"[CodeAgent] 教学注释添加完成，长度={len(explained)} 字符")
            return {
                "code_content": code_content,
                "detected_language": language,
                "explained_content": explained,
                "is_valid": True,
            }
        except Exception as e:
            logger.error(f"[CodeAgent] 添加注释失败: {e}")
            # 即使“教学讲解增强”失败，也不要丢掉前面好不容易生成出的代码。
            return {
                "code_content": code_content,
                "detected_language": language,
                "explained_content": code_content,
                "is_valid": True,
            }

    async def _fallback_generate_code(self, state: CodeState) -> dict[str, Any]:
        # 图工作流失败时，退回最保守的一次性 LLM 产出，至少保证有一份 Python 示例。
        prompt = (
            "你是一位编程教学专家。请直接生成一个完整、可运行的 Markdown 代码案例，"
            "不要调用工具，不要输出计划，不要追问用户。\n\n"
            f"专业：{state.get('major', '通用')}\n"
            f"课程：{state.get('course', '')}\n"
            f"主题：{state.get('topic', '')}\n"
            f"知识短板：{state.get('gap', '')}\n"
            f"知识水平：{state.get('user_profile', {}).get('knowledge_level', '中等')}\n"
            "要求：\n"
            "1. 使用 Python\n"
            "2. 输出结构必须包含：问题场景、完整代码、运行结果、关键点解析\n"
            "3. 代码块使用 ```python 标记\n"
            "4. 示例要适合初学者并可直接运行\n"
        )
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip() if isinstance(response.content, str) else str(response.content)
        return {
            "explained_content": content,
            "code_content": content,
            "detected_language": _detect_language(content),
            "error": None,
        }

    async def generate_code(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[CodeAgent] 收到生成请求: topic={topic}")
        await self._ensure_graph()

        # 初始状态只保留本次运行必需字段，避免上一轮结果污染当前任务。
        initial_state: CodeState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "code_content": "",
            "detected_language": "unknown",
            "explained_content": "",
            "is_valid": False,
            "validation_feedback": "",
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
        }

        try:
            logger.info("[CodeAgent] 开始执行 LangGraph 工作流")
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial_state, {"recursion_limit": 15}),
                timeout=90,
            )
            logger.info("[CodeAgent] 工作流执行完成: keys=%s", sorted(result.keys()))
        except Exception as e:
            logger.error(f"[CodeAgent] 工作流执行失败: {e}")
            try:
                logger.info("[CodeAgent] 进入降级生成流程")
                result = await self._fallback_generate_code(initial_state)
            except Exception as fallback_error:
                return {"success": False, "content": "", "detected_language": "unknown", "code_only": "", "error": str(fallback_error)}

        explained = result.get("explained_content", "") or result.get("code_content", "")
        # 前端展示可以用 explained，运行器或调试器更适合消费纯 code_only。
        code_only = _extract_code_block(result.get("code_content", ""))
        language = result.get("detected_language", "unknown")
        if not explained:
            try:
                logger.warning("[CodeAgent] 工作流无有效输出，尝试最终兜底生成")
                fallback = await self._fallback_generate_code(initial_state)
                explained = fallback.get("explained_content", "")
                code_only = _extract_code_block(fallback.get("code_content", ""))
                language = fallback.get("detected_language", language)
            except Exception as fallback_error:
                logger.error(f"[CodeAgent] 降级生成失败: {fallback_error}")
        file_path = None
        if explained:
            file_path = self._save_to_workplace("code", topic, explained, "md")
            logger.info("[CodeAgent] 代码案例已保存: file_path=%s language=%s", file_path, language)

        return {
            "success": bool(explained),
            "content": explained,
            "file_path": file_path,
            "detected_language": language,
            "code_only": code_only,
            "error": result.get("error") if not explained else None,
        }
