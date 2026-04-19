"""
内容创作 Agent：生成个性化专业课程讲解文档。
基于 BaseResourceAgent 实现，并使用黑板模式与用户画像。
"""

import asyncio
import json
import shlex
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode


from app.infra.llm import get_deepseek_chat_llm
from app.infra.logging import get_logger
from app.config import CONTENT_AGENT_TIMEOUT_SECONDS, CONTENT_LLM_TIMEOUT
from app.resource.base_agent import BaseResourceAgent, BaseAgentState
from app.shared.json_utils import parse_first_json_object
from app.tools.file_operator import save_to_workplace

logger = get_logger(__name__)


class ContentState(BaseAgentState):
    current_step: str
    outline: str
    content: str
    skill_context: str


def _extract_json(text: str) -> dict:
    try:
        return parse_first_json_object(text)
    except Exception:
        # 审查失败时允许走降级：上游会把它当作“不通过”并重试或放行
        # 这里不使用正则抽取 JSON，避免通过 regex “抠 JSON”。
        return {"passed": False, "feedback": "无法解析审查结果"}


_REVIEW_PROMPT = (
    "你是一位教学文档质量审查专家。请审查以下课程讲解文档的质量。\n\n"
    "## 审查标准\n"
    "1. 字数检查：文档正文应在 1500-3000 字之间\n"
    "2. 结构完整性：是否包含 概述、核心讲解、案例分析、常见误区、总结 等主要章节\n"
    "3. 内容针对性：是否围绕主题 {topic} 深入展开，而非泛泛而谈\n"
    "4. 个性化匹配：是否考虑了用户画像中描述的学习特点\n"
    "5. 案例质量：是否包含至少一个完整的实际案例\n\n"
    "## 待审查文档\n"
    "{content}\n\n"
    "## 大纲\n"
    "{outline}\n\n"
    "## 输出要求\n"
    "请严格按以下 JSON 格式输出审查结论，不要包含代码围栏：\n"
    '{{"passed": true/false, "feedback": "如果不通过，说明具体原因和改进建议"}}'
)


class ContentWriter(BaseResourceAgent):
    """个性化课程讲解文档生成 Agent。"""

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "list_directory", "file_tree", "find_files", "get_file_info",
        "save_docx_file", "extract_pdf_text",
    ]
    skill_names = ["docx", "pdf"]
    _TEXT_ASSET_EXTS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".toml", ".ini", ".xml", ".html"}
    def __init__(self) -> None:
        super().__init__(
            name="ContentAgent",
            agent_dir=Path(__file__).parent,
            state_schema=ContentState,
            temperature=0.3,
        )
        self.llm = get_deepseek_chat_llm(temperature=0.3)

    @staticmethod
    def _workflow_timeout_seconds() -> int:
        """Allow enough time for outline + content + review, while staying configurable."""
        # 内容 Agent 需要经历“大纲 -> 正文 -> 审查”三轮，因此超时阈值单独拉高。
        return CONTENT_AGENT_TIMEOUT_SECONDS

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        ctx = ""
        # 把思维导图的骨架提前注入正文 Agent，减少正文结构跑偏。
        if "mindmap" in shared_memory:
            mm = shared_memory["mindmap"].get("agent_output", "")
            if mm: ctx += f"【思维导图核心结构】\n{mm}\n"
        return ctx

    async def _build_graph(self):
        """P1：override 父类默认图拓扑，插入 step_router 节点实现分步生成。"""
        # self._tools 已由 _load_tools() 填充，无需重复初始化
        graph = StateGraph(self.state_schema)

        # agent 负责与 LLM 交互，tools 执行工具，step_router 在“大纲/正文”之间切换，
        # validate 做最终质量审查。
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tools_node)
        graph.add_node("step_router", self._step_router_node)
        graph.add_node("validate", self._validate_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._custom_tools_condition)
        graph.add_edge("tools", "agent")

        graph.add_conditional_edges(
            "step_router",
            self._step_router_condition,
            {"agent": "agent", "validate": "validate"}
        )
        graph.add_conditional_edges(
            "validate",
            self._should_retry,
            path_map={"end": END, "retry": "agent"},
        )
        compiled = graph.compile()
        logger.info(f"[{self.name}] StateGraph 构建完成 (含 step_router, 工具数: {len(self._tools)})")
        return compiled

    async def _tools_node(self, state: Any) -> dict:
        """Wrap ToolNode so ContentAgent can log tool calls and outputs explicitly."""
        messages = state.get("messages", [])
        last_ai = messages[-1] if messages and isinstance(messages[-1], AIMessage) else None
        pending_calls = list(getattr(last_ai, "tool_calls", []) or [])
        if pending_calls:
            logger.info(
                "[ContentAgent] 即将执行工具: names=%s args=%s",
                [call.get("name", "unknown") for call in pending_calls],
                [call.get("args", {}) for call in pending_calls],
            )

        tool_node = ToolNode(self._tools)
        result = await tool_node.ainvoke(state)

        output_messages = result.get("messages", []) if isinstance(result, dict) else []
        for msg in output_messages:
            if isinstance(msg, ToolMessage):
                logger.info(
                    "[ContentAgent] 工具执行完成: name=%s tool_call_id=%s output_preview=%r",
                    getattr(msg, "name", "unknown"),
                    getattr(msg, "tool_call_id", ""),
                    str(msg.content)[:300],
                )
        return result

    def _custom_tools_condition(self, state: Any) -> str:
        messages = state.get("messages", [])
        # 只要最后一条 AI 消息声明了 tool_calls，就先进入 tools 节点消费工具调用。
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "tools"
        return "step_router"

    def _step_router_condition(self, state: Any) -> str:
        step = state.get("current_step", "outline")
        # 第一步先拿到大纲；拿到大纲但还没有正文时，再回到 agent 继续扩写正文。
        if step == "outline":
            return "agent"
        if step == "content" and state.get("outline") and not state.get("content"):
            return "agent"
        return "validate"

    def _build_system_message(self, state: Any) -> str:
        """构建 System Prompt（返回字符串）。"""
        system_prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", ""),
            topic=state.get("topic", ""),
            user_profile="",
        )
        skill_context = (state.get("skill_context") or "").strip()
        if skill_context:
            system_prompt += (
                "\n\n## 文档技能资产（必须优先参考）\n"
                "以下内容来自 docx/pdf skills 的指令、示例和可执行脚本，"
                "写作时必须遵循其规范并吸收其结构风格：\n"
                f"{skill_context}"
            )
        return self._append_context_to_prompt(system_prompt, state)

    def _build_initial_human_message(self, state: Any) -> str:
        """ContentWriter 使用分步生成，此方法由 _agent_node 动态调用。"""
        return ""

    def _save_to_workplace(self, sub_dir: str, topic: str, content: str, ext: str = "md") -> str:
        # 统一走共享 save_to_workplace，保持所有资源文件的命名和保存位置一致。
        result = save_to_workplace.invoke(
            {
                "sub_dir": sub_dir,
                "topic": topic,
                "content": content,
                "ext": ext,
            }
        )
        return result if isinstance(result, str) else str(result)

    @staticmethod
    def _build_content_request(outline: str) -> str:
        outline_text = outline.strip() or "请沿用你刚刚生成的大纲结构。"
        # 第二轮提示词只做一件事：强制模型沿着已有大纲写完整正文。
        return (
            "请根据以下大纲撰写完整的专业讲解文档（1500-3000字），严格遵循大纲结构，每个章节都要有充实的内容。"
            "不要向用户追问补充信息，直接完成正文写作。\n\n"
            f"现有大纲：\n{outline_text}"
        )

    @staticmethod
    def _looks_like_refusal(content: str) -> bool:
        text = (content or "").strip()
        if not text:
            return True
        refusal_markers = (
            "无法按照要求完成",
            "无法完成",
            "请补充",
            "请您补充",
            "未提供具体的大纲",
            "未提供大纲",
            "请提供大纲",
            "需要更多信息",
        )
        return any(marker in text for marker in refusal_markers)

    @classmethod
    def _needs_content_recovery(cls, content: str) -> bool:
        text = (content or "").strip()
        if cls._looks_like_refusal(text):
            return True
        return len(text) < 500

    @staticmethod
    def _parse_bullet_items(text: str) -> list[str]:
        items: list[str] = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item and item != "(none)":
                    items.append(item)
        return items

    @staticmethod
    def _trim_text(text: str, limit: int = 2500) -> str:
        value = text or ""
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n...(已截断，共 {len(value)} 字符)"

    async def _call_tool_safely(self, tool_name: str, payload: dict[str, Any]) -> str:
        tool_map = {tool.name: tool for tool in (self._tools or [])}
        tool_obj = tool_map.get(tool_name)
        if not tool_obj:
            logger.warning("[ContentAgent] 技能工具不存在: %s", tool_name)
            return ""
        try:
            result = await tool_obj.ainvoke(payload)
            if isinstance(result, str):
                return result
            return str(result)
        except Exception as exc:
            logger.warning("[ContentAgent] 技能工具调用失败: tool=%s error=%s", tool_name, exc)
            return ""

    async def _prepare_skill_context(self) -> tuple[str, dict[str, Any]]:
        """主动加载技能指令、脚本、示例、参考资料和资产，避免只依赖 SKILL.md。"""
        sections: list[str] = []
        usage_report: dict[str, Any] = {"skills": {}}

        for skill_name in self.skill_names:
            skill_report: dict[str, Any] = {
                "loaded_instruction": False,
                "read_scripts": [],
                "read_examples": [],
                "read_references": [],
                "read_assets": [],
                "listed_scripts": [],
            }

            instruction_text = await self._call_tool_safely(
                "skill",
                {"name": skill_name, "include_resources": False},
            )
            instruction_excerpt = self._trim_text(instruction_text, limit=1800)
            if instruction_excerpt:
                skill_report["loaded_instruction"] = True

            examples_listing = await self._call_tool_safely(
                "skill_read",
                {"name": skill_name, "kind": "examples", "relative_path": ""},
            )
            example_files = self._parse_bullet_items(examples_listing)[:3]
            example_chunks: list[str] = []
            for rel_path in example_files:
                content = await self._call_tool_safely(
                    "skill_read",
                    {
                        "name": skill_name,
                        "kind": "examples",
                        "relative_path": rel_path,
                        "max_chars": 1600,
                    },
                )
                if content:
                    example_chunks.append(f"示例文件 `{rel_path}`:\n{self._trim_text(content, limit=1600)}")
                    skill_report["read_examples"].append(rel_path)

            reference_listing = await self._call_tool_safely(
                "skill_read",
                {"name": skill_name, "kind": "references", "relative_path": ""},
            )
            reference_files = self._parse_bullet_items(reference_listing)[:2]
            reference_chunks: list[str] = []
            for rel_path in reference_files:
                content = await self._call_tool_safely(
                    "skill_read",
                    {
                        "name": skill_name,
                        "kind": "references",
                        "relative_path": rel_path,
                        "max_chars": 1500,
                    },
                )
                if content:
                    reference_chunks.append(f"参考文件 `{rel_path}`:\n{self._trim_text(content, limit=1500)}")
                    skill_report["read_references"].append(rel_path)

            asset_listing = await self._call_tool_safely(
                "skill_read",
                {"name": skill_name, "kind": "assets", "relative_path": ""},
            )
            asset_files = self._parse_bullet_items(asset_listing)[:2]
            asset_chunks: list[str] = []
            for rel_path in asset_files:
                if Path(rel_path).suffix.lower() not in self._TEXT_ASSET_EXTS:
                    continue
                content = await self._call_tool_safely(
                    "skill_read",
                    {
                        "name": skill_name,
                        "kind": "assets",
                        "relative_path": rel_path,
                        "max_chars": 1200,
                    },
                )
                if content:
                    asset_chunks.append(f"资产文件 `{rel_path}`:\n{self._trim_text(content, limit=1200)}")
                    skill_report["read_assets"].append(rel_path)

            script_listing = await self._call_tool_safely("skill_run", {"name": skill_name, "script_path": ""})
            script_files = self._parse_bullet_items(script_listing)[:8]
            if script_files:
                skill_report["listed_scripts"] = script_files

            script_chunks: list[str] = []
            for rel_path in script_files[:2]:
                script_content = await self._call_tool_safely(
                    "skill_read",
                    {
                        "name": skill_name,
                        "kind": "scripts",
                        "relative_path": rel_path,
                        "max_chars": 1200,
                    },
                )
                if script_content:
                    script_chunks.append(f"脚本 `{rel_path}`:\n{self._trim_text(script_content, limit=1200)}")
                    skill_report["read_scripts"].append(rel_path)

            section_lines = [
                f"### 技能 `{skill_name}`",
                "- 调用方式: `skill / skill_read / skill_run`",
            ]
            if instruction_excerpt:
                section_lines.append("指令要点:")
                section_lines.append(instruction_excerpt)
            if reference_chunks:
                section_lines.append("参考资料:")
                section_lines.extend(reference_chunks)
            if example_chunks:
                section_lines.append("示例参考:")
                section_lines.extend(example_chunks)
            if asset_chunks:
                section_lines.append("模板/资产:")
                section_lines.extend(asset_chunks)
            if script_files:
                section_lines.append("可执行脚本清单:")
                section_lines.append("\n".join(f"- `{script}`" for script in script_files))
            if script_chunks:
                section_lines.append("脚本实现片段:")
                section_lines.extend(script_chunks)

            usage_report["skills"][skill_name] = skill_report
            sections.append("\n".join(section_lines))

        skill_context = self._trim_text("\n\n".join(sections), limit=10000)
        return skill_context, usage_report

    async def _run_skill_postprocess(
        self,
        docx_path: str | None,
        pdf_path: str | None,
    ) -> dict[str, str]:
        """文档生成后调用技能脚本做基础校验。"""
        postprocess: dict[str, str] = {}
        if docx_path:
            docx_output = await self._call_tool_safely(
                "skill_run",
                {
                    "name": "docx",
                    "script_path": "scripts/office/validate.py",
                    "script_args": shlex.quote(docx_path),
                    "timeout_sec": 90,
                },
            )
            if docx_output:
                postprocess["docx_validate"] = self._trim_text(docx_output, limit=2500)

        if pdf_path:
            pdf_output = await self._call_tool_safely(
                "skill_run",
                {
                    "name": "pdf",
                    "script_path": "scripts/check_fillable_fields.py",
                    "script_args": shlex.quote(pdf_path),
                    "timeout_sec": 60,
                },
            )
            if pdf_output:
                postprocess["pdf_check_fillable_fields"] = self._trim_text(pdf_output, limit=2000)

        return postprocess

    async def _agent_node(self, state: Any) -> dict:
        messages = state.get("messages", [])
        current_step = state.get("current_step", "outline")
        retry_count = state.get("retry_count", 0)
        feedback = state.get("validation_feedback", "")
        outline = state.get("outline", "")

        logger.info(f"[ContentAgent] _agent_node: step={current_step}, retry={retry_count}")

        if current_step == "outline" and not messages:
            # 首轮只要求模型先产出大纲，降低一次性直接写长文失败的概率。
            sys_prompt = self._build_system_message(state)
            human_text = "请先为这份讲解文档生成一份详细的大纲（列出各章节标题及每节要点的简短描述）。"
            messages = [SystemMessage(content=sys_prompt), HumanMessage(content=human_text)]
        elif current_step == "outline" and retry_count > 0 and feedback and len(messages) < 3:
            # 如果大纲阶段就被打回，这里把审查反馈显式喂回去，要求重写大纲。
            messages.append(HumanMessage(
                content=f"上一次文档未通过审查，原因：{feedback}\n请根据上述反馈修正大纲后重新生成。"
            ))
        elif current_step == "content" and retry_count > 0 and feedback:
            # 正文阶段重试时，保留已有大纲，只让模型根据反馈修正文案。
            messages.append(HumanMessage(
                content=(
                    f"上一次正文未通过审查，原因：{feedback}\n"
                    "请基于现有大纲重新撰写完整的专业讲解文档，不要向用户追问额外信息。\n\n"
                    f"现有大纲：\n{outline or '请沿用你刚刚生成的大纲结构。'}"
                )
            ))
        elif current_step == "content" and not any("撰写完整的专业讲解文档" in str(m.content) for m in messages):
            # 第一次进入正文阶段时，补一条“按大纲扩写”的 HumanMessage。
            messages.append(HumanMessage(content=self._build_content_request(outline)))

        llm_with_tools = self.llm.bind_tools(self._tools) if self._tools else self.llm

        # 规范化结构化 ToolMessage 内容，避免部分模型接口拒绝 list 类型 content
        from app.shared.sanitizers import sanitize_tool_messages
        messages = sanitize_tool_messages(messages)

        logger.info(
            "[ContentAgent] 调用 LLM: step=%s message_count=%d outline_len=%d feedback=%r",
            current_step,
            len(messages),
            len(outline),
            feedback[:200],
        )
        llm_timeout = CONTENT_LLM_TIMEOUT
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(messages),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("[ContentAgent] LLM 调用超时: step=%s timeout=%ds", current_step, llm_timeout)
            return {"error": f"LLM 调用超时 ({llm_timeout}s)", "is_valid": False}
        if isinstance(response, AIMessage) and getattr(response, "tool_calls", None):
            logger.info(
                "[ContentAgent] LLM 选择工具: names=%s args=%s",
                [call.get("name", "unknown") for call in response.tool_calls],
                [call.get("args", {}) for call in response.tool_calls],
            )
        logger.info(
            "[ContentAgent] LLM 返回: step=%s tool_calls=%s content_preview=%r",
            current_step,
            bool(getattr(response, "tool_calls", None)),
            (response.content or "")[:300] if isinstance(response.content, str) else str(response.content)[:300],
        )

        return {"messages": [response]}

    async def _step_router_node(self, state: Any) -> dict:
        messages = state.get("messages", [])
        current_step = state.get("current_step", "outline")

        last_content = ""
        if messages and isinstance(messages[-1], AIMessage):
            content = messages[-1].content
            if isinstance(content, str):
                last_content = content.strip()
            else:
                last_content = str(content).strip()

        if current_step == "outline":
            # 大纲阶段结束后，把大纲落回状态，并切换到正文阶段。
            logger.info(f"[ContentAgent] 大纲生成完成，长度={len(last_content)}, 预览={last_content[:200]!r}")
            return {"outline": last_content, "current_step": "content"}
        else:
            # 正文阶段结束后，只回填 content，后续交给 validate 做质量判定。
            logger.info(f"[ContentAgent] 文档扩展完成，长度={len(last_content)}, 预览={last_content[:200]!r}")
            return {"content": last_content}

    async def _validate_node(self, state: Any) -> dict:
        content = state.get("content", "")
        outline = state.get("outline", "")
        error = state.get("error")

        if error or not content:
            logger.warning(
                "[ContentAgent] 校验未通过: error=%r content_len=%d outline_len=%d",
                error,
                len(content),
                len(outline),
            )
            return {
                "is_valid": False,
                "validation_feedback": error or "未生成正文，请基于现有大纲直接补全完整讲解文档，不要追问用户。",
                "retry_count": state.get("retry_count", 0) + 1,
                "current_step": "content" if outline else "outline",
            }

        logger.info("[ContentAgent] _validate_node: 开始质量审查")

        word_count = len(content)
        # 先做本地快速校验，避免每次都再额外调用一次评审模型。
        if word_count < 800:
            logger.warning("[ContentAgent] 正文字数不足: %d", word_count)
            return {
                "is_valid": False,
                "validation_feedback": f"文档字数仅 {word_count} 字，远低于 1500 字的最低要求，请大幅扩展。",
                "retry_count": state.get("retry_count", 0) + 1,
                "current_step": "content",
            }

        prompt = _REVIEW_PROMPT.format(
            topic=state.get("topic", ""),
            content=content[:3000],
            outline=outline[:1000],
        )

        try:
            # 审查输出必须是 JSON：优先启用 JSON Mode（OpenAI 兼容 response_format）。
            try:
                review_llm = self.llm.bind(response_format={"type": "json_object"})
                response = await review_llm.ainvoke([HumanMessage(content=prompt)])
            except Exception as exc:
                logger.warning("[ContentAgent] 审查 JSON Mode 不支持，fallback=plain error=%s", exc, exc_info=exc)
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            review = _extract_json(response.content)
            passed = review.get("passed", False)
            feedback = review.get("feedback", "")

            logger.info(f"[ContentAgent] 审查结果: passed={passed}, feedback={feedback}")
            return {
                "is_valid": passed,
                "validation_feedback": feedback,
                "retry_count": state.get("retry_count", 0) + 1 if not passed else state.get("retry_count", 0),
                "current_step": "content",
            }
        except Exception as e:
            logger.exception("[ContentAgent] 审查失败")
            return {"is_valid": True, "validation_feedback": ""}

    async def _fallback_generate_content(self, state: ContentState) -> dict[str, Any]:
        # 当图工作流超时或审查链路异常时，降级为一次性长文生成，保证至少给用户返回可读内容。
        prompt = (
            "你是一位高校课程讲解文档作者。请直接生成一份完整的 Markdown 课程讲解文档，"
            "不要追问用户，不要输出额外说明。\n\n"
            f"专业：{state.get('major', '通用')}\n"
            f"课程：{state.get('course', '')}\n"
            f"主题：{state.get('topic', '')}\n"
            f"知识短板：{state.get('gap', '')}\n"
            f"参考大纲：\n{state.get('outline', '') or '请按标准教学文档结构自行组织'}\n"
            "要求：\n"
            "1. 必须包含：概述、核心讲解、案例分析、常见误区、总结\n"
            "2. 字数尽量充实，至少 1200 字\n"
            "3. 面向初学者，讲解清晰具体\n"
            "4. 直接输出最终 Markdown 文档\n"
            "5. 严禁向用户索要补充信息，必须直接完成全文\n"
            "6. 控制在 1500-3000 字之间，不要过长\n"
        )
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip() if isinstance(response.content, str) else str(response.content)
        outline = "1. 概述\n2. 核心讲解\n3. 案例分析\n4. 常见误区\n5. 总结"
        return {"content": content, "outline": outline, "error": None}

    async def generate_content(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[ContentAgent] 收到生成请求: topic={topic}")
        await self._ensure_graph()
        start_time = time.perf_counter()
        timeout_seconds = self._workflow_timeout_seconds()
        skill_context, skill_usage_report = await self._prepare_skill_context()

        initial_state: ContentState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "current_step": "outline",
            "outline": "",
            "content": "",
            "is_valid": False,
            "validation_feedback": "",
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
            "skill_context": skill_context,
        }

        try:
            logger.info("[ContentAgent] 开始执行工作流: timeout=%ss topic=%r", timeout_seconds, topic)
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial_state, {"recursion_limit": 20}),
                timeout=timeout_seconds,
            )
            logger.info(
                "[ContentAgent] 工作流执行完成: elapsed=%.2fs keys=%s content_len=%d outline_len=%d",
                time.perf_counter() - start_time,
                sorted(result.keys()),
                len(result.get("content", "") or ""),
                len(result.get("outline", "") or ""),
            )
        except asyncio.TimeoutError:
            logger.exception(
                "[ContentAgent] 工作流执行超时: timeout=%ss elapsed=%.2fs topic=%r",
                timeout_seconds,
                time.perf_counter() - start_time,
                topic,
            )
            try:
                logger.info("[ContentAgent] 尝试降级生成正文")
                result = await self._fallback_generate_content(initial_state)
            except Exception as fallback_error:
                logger.exception("[ContentAgent] 超时后的降级生成失败")
                return {
                    "success": False,
                    "content": "",
                    "file_path": None,
                    "outline": "",
                    "error": str(fallback_error),
                }
        except Exception:
            logger.exception(
                "[ContentAgent] 工作流执行失败: elapsed=%.2fs topic=%r",
                time.perf_counter() - start_time,
                topic,
            )
            try:
                logger.info("[ContentAgent] 尝试降级生成正文")
                result = await self._fallback_generate_content(initial_state)
            except Exception as fallback_error:
                logger.exception("[ContentAgent] 异常后的降级生成失败")
                return {
                    "success": False,
                    "content": "",
                    "file_path": None,
                    "outline": "",
                    "error": str(fallback_error),
                }

        content = result.get("content", "")
        outline = result.get("outline", "")
        if self._needs_content_recovery(content):
            try:
                logger.warning(
                    "[ContentAgent] 正文需要补救: content_len=%d refusal=%s，尝试降级补全",
                    len(content or ""),
                    self._looks_like_refusal(content),
                )
                # 这里复用已有 outline，尽量让降级内容仍然贴合前面已经规划出的结构。
                initial_state["outline"] = outline
                fallback = await self._fallback_generate_content(initial_state)
                content = fallback.get("content", "")
                outline = fallback.get("outline", outline)
            except Exception as fallback_error:
                logger.exception("[ContentAgent] 降级生成失败")
        if self._needs_content_recovery(content):
            logger.error("[ContentAgent] 补救后正文仍不可用，判定生成失败")
            content = ""

        success = bool(content)
        file_path = None
        docx_path = None
        pdf_path = None
        skill_postprocess: dict[str, str] = {}
        if success:
            file_path = self._save_to_workplace("content", topic, content, "md")
            try:
                saved_content = Path(file_path).read_text(encoding="utf-8")
                if saved_content.strip():
                    content = saved_content
            except Exception:
                logger.exception("[ContentAgent] 文档已保存，但回读文件失败: %s", file_path)
            logger.info(
                "[ContentAgent] 文档生成成功: file_path=%s content_len=%d outline_len=%d elapsed=%.2fs",
                file_path,
                len(content),
                len(outline),
                time.perf_counter() - start_time,
            )

            # 额外生成 DOCX 和 PDF 格式
            try:
                from app.tools.document_executor import save_docx_file
                docx_result = json.loads(save_docx_file.invoke({"title": topic, "content": content}))
                docx_path = docx_result.get("file_path")
                logger.info("[ContentAgent] DOCX 已生成: %s", docx_path)
            except Exception:
                logger.exception("[ContentAgent] DOCX 生成失败")

            try:
                from app.tools.document_executor import save_pdf_file
                pdf_result = json.loads(save_pdf_file.invoke({"title": topic, "content": content}))
                pdf_path = pdf_result.get("file_path")
                logger.info("[ContentAgent] PDF 已生成: %s", pdf_path)
            except Exception:
                logger.exception("[ContentAgent] PDF 生成失败")

            try:
                skill_postprocess = await self._run_skill_postprocess(docx_path, pdf_path)
            except Exception:
                logger.exception("[ContentAgent] 技能后处理脚本执行失败")

        else:
            logger.error(
                "[ContentAgent] 文档生成失败: outline_len=%d error=%r elapsed=%.2fs",
                len(outline),
                result.get("error"),
                time.perf_counter() - start_time,
            )

        return {
            "success": success,
            "content": content,
            "outline": outline,
            "file_path": file_path,
            "docx_path": docx_path,
            "pdf_path": pdf_path,
            "skill_usage_report": skill_usage_report,
            "skill_postprocess": skill_postprocess,
            "error": result.get("error") if not success else None,
        }
