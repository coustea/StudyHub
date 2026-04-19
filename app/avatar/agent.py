# -*- coding: utf-8 -*-
"""
AvatarAgent — 数字人独立 LangGraph 智能体

与 TutorAgent 对等但独立的 Agent：
- 独立的 LangGraph StateGraph 和 system prompt
- 复用 tools/registry、skills/manager、infra/llm 等共享基础设施
- 独立的记忆（source="avatar_fact"），共享画像
- 输出适配：口语化文本 + 工具事件
"""

from __future__ import annotations

import asyncio

from typing import Annotated, Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.infra.logging import get_logger
from app.infra.llm import get_llm, get_fast_llm, get_glm_vision_llm
from app.shared.agent_context import AgentContextService
from app.shared.vision import build_vision_service

logger = get_logger(__name__)

# AvatarAgent 可使用的工具名称（与 TutorAgent 共享注册表）
AVATAR_TOOL_NAMES: list[str] = [
    "create_document_file",
    "read_uploaded_file",
    "list_uploaded_files",
    "save_to_workplace",
    "read_file_safe",
    "write_file",
    "edit_file",
    "append_file",
    "read_file_lines",
]

# 搜索关键词（与 TutorAgent 分类逻辑一致）
SEARCH_KEYWORDS = (
    "搜索", "搜一下", "查一下", "查找", "检索", "帮我找", "网上", "近几年", "最新",
)


class AvatarState(TypedDict, total=False):
    """AvatarAgent LangGraph 状态"""
    user_id: int
    session_id: str
    image_urls: Optional[list[str]]
    file_urls: Optional[list[str]]
    route: str  # "direct" | "tool_needed" | "vision_needed"
    system_prompt: str
    tool_system_prompt: str
    messages: Annotated[list[AnyMessage], add_messages]
    input_source: str  # "asr" | "text"


AVATAR_SYSTEM_PROMPT = """你是一个数字人辅导教师，通过语音和视频与学生实时交互。

## 核心规则
- 回复必须口语化，适合语音播报
- 句子简短（每句不超过 30 字），自然分段
- 使用自然的语气词（"好的"、"我来给你讲讲"、"是这样"）
- 不要使用 Markdown 格式（语音无法渲染标题、列表等）
- 遇到复杂的工具调用结果，用简短口语提示学生查看屏幕上的卡片
- 对学生保持鼓励、耐心、专业的态度

## ASR 输入处理
当 input_source 为 "asr" 时：
- 容忍口语化表达和可能的识别错误
- 如果用户意图不明确，简短追问而非猜测

## 学习者画像
{profile_context}

## 相关记忆
{fact_context}

## 最近对话
{recent_chat_context}
"""

AVATAR_TOOL_SYSTEM_PROMPT = """你是一个数字人辅导教师，通过语音和视频与学生实时交互。

## 核心规则
- 回复口语化，适合语音播报
- 句子简短（每句不超过 30 字）
- 不使用 Markdown 格式
- 工具调用结果用口语简述，引导学生查看屏幕卡片

## ASR 输入处理
当 input_source 为 "asr" 时，容忍口语化表达和识别错误。

## 学习者画像
{profile_context}

## 相关记忆
{fact_context}

## 最近对话
{recent_chat_context}

## 可用工具
{skills_context}

## 附件信息
{file_info_context}
"""

AVATAR_CLASSIFIER_PROMPT = """判断以下用户消息需要直接回答还是需要调用工具。

需要工具的情况：需要搜索、查资料、创建文件、读文件、写代码等操作。
直接回答的情况：简单的知识问答、闲聊、解释概念等。

用户消息：{user_message}
是否有附件：{has_attachments}

只回复 "direct" 或 "tool_needed"，不要回复其他内容。"""


def _lazy_import_tools():
    """延迟导入工具注册表，避免循环导入"""
    from app.tools.registry import get_many
    from app.tools import _ensure_tools_loaded  # type: ignore
    _ensure_tools_loaded()
    return get_many(AVATAR_TOOL_NAMES)


class AvatarAgent:
    """数字人 Agent — 独立 LangGraph 图"""

    def __init__(self) -> None:
        self.llm = get_llm(temperature=0.7, streaming=True)
        self.classifier_llm = get_fast_llm(temperature=0.0, max_tokens=100)
        self.ctx_service = AgentContextService(module_name="avatar")
        self.vision_service = build_vision_service(get_glm_vision_llm())
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        graph = StateGraph(AvatarState)

        # 添加节点
        graph.add_node("classify", self._classify_node)
        graph.add_node("direct_answer", self._direct_answer_node)
        graph.add_node("vision_answer", self._vision_answer_node)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tools_node)

        # 边
        graph.set_entry_point("classify")
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {
                "direct": "direct_answer",
                "vision_needed": "vision_answer",
                "tool_needed": "agent",
            },
        )
        graph.add_edge("direct_answer", END)
        graph.add_edge("vision_answer", END)
        graph.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def chat_stream(
        self,
        user_id: int,
        session_id: str,
        user_message: str | None = None,
        user_text: str | None = None,
        profile_ctx: str | None = None,
        memory_ctx: str | None = None,
        chat_ctx: list[AnyMessage] | None = None,
        input_source: str = "text",
        image_urls: list[str] | None = None,
        file_urls: list[str] | None = None,
        attachment_analysis: dict[str, Any] | None = None,
    ):
        """流式生成 — yield 事件字典

        事件类型：
        - {"type": "text_chunk", "content": "..."}
        - {"type": "tool_result", "data": {...}}
        - {"type": "tool_error", "data": "..."}
        """
        text = (user_message if user_message is not None else user_text) or ""
        image_urls = image_urls or []
        file_urls = file_urls or []
        attachment_analysis_context = str((attachment_analysis or {}).get("analysis_context", "")).strip()

        if chat_ctx is None:
            _, recent_chat_context = await self.ctx_service.build_chat_ctx(
                user_id=user_id,
                session_id=session_id,
                user_message=text,
                image_urls=image_urls,
                file_urls=file_urls,
            )
            chat_ctx = []
        else:
            recent_chat_context = self._format_chat_ctx(chat_ctx)

        if profile_ctx is None or memory_ctx is None:
            built_profile_ctx, built_memory_ctx = await asyncio.gather(
                self.ctx_service.build_profile_ctx(user_id),
                self.ctx_service.build_memory_ctx(user_id),
            )
            profile_ctx = profile_ctx if profile_ctx is not None else built_profile_ctx
            memory_ctx = memory_ctx if memory_ctx is not None else built_memory_ctx

        # 构建技能上下文
        skills_ctx = self._build_skills_context()
        analysis_hint = (
            "\n\n## 附件并行预分析结果（上传后自动生成，可直接参考）\n"
            f"{attachment_analysis_context}\n"
            if attachment_analysis_context
            else ""
        )

        # 填充 prompt
        system_prompt = AVATAR_SYSTEM_PROMPT.format(
            profile_context=profile_ctx or "暂无",
            fact_context=memory_ctx or "暂无",
            recent_chat_context=recent_chat_context,
        ) + analysis_hint
        tool_system_prompt = AVATAR_TOOL_SYSTEM_PROMPT.format(
            profile_context=profile_ctx or "暂无",
            fact_context=memory_ctx or "暂无",
            recent_chat_context=recent_chat_context,
            skills_context=skills_ctx,
            file_info_context=self._build_file_ctx(image_urls, file_urls),
        ) + analysis_hint

        initial_state = AvatarState(
            user_id=user_id,
            session_id=session_id,
            image_urls=image_urls,
            file_urls=file_urls,
            input_source=input_source,
            route="",
            system_prompt=system_prompt,
            tool_system_prompt=tool_system_prompt,
            messages=[HumanMessage(content=text)],
        )

        full_response = ""

        async for event in self._graph.astream_events(
            initial_state,
            version="v2",
            config={"recursion_limit": 15},
        ):
            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    full_response += chunk.content
                    yield {"type": "text_chunk", "content": chunk.content}

            elif kind == "on_chain_end":
                name = event.get("name", "")
                if name in ("vision_answer", "direct_answer"):
                    output = event.get("data", {}).get("output", {})
                    msgs = output.get("messages", []) if isinstance(output, dict) else []
                    if msgs:
                        last = msgs[-1]
                        if hasattr(last, "content") and last.content and not full_response:
                            full_response = last.content
                            yield {"type": "text_chunk", "content": last.content}

            elif kind == "on_tool_end":
                tool_output = event.get("data", {}).get("output", "")
                tool_name = ""
                # 尝试获取工具名
                tags = event.get("tags", [])
                for tag in tags:
                    if tag.startswith("langchain_tool:"):
                        tool_name = tag.split(":")[-1]
                        break
                yield {
                    "type": "tool_result",
                    "data": {
                        "tool_name": tool_name,
                        "result": str(tool_output) if tool_output else "",
                    },
                }

            elif kind == "on_tool_error":
                yield {
                    "type": "tool_error",
                    "data": str(event.get("data", {}).get("error", "工具调用失败")),
                }

        yield {"type": "complete", "full_response": full_response}

    # ---- 节点方法 ----

    async def _classify_node(self, state: AvatarState) -> dict:
        """分类节点：direct / tool_needed / vision_needed"""
        messages = state.get("messages", [])
        user_msg = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                user_msg = m.content
                break

        # 硬规则
        if state.get("file_urls"):
            return {"route": "tool_needed"}

        if any(kw in user_msg for kw in SEARCH_KEYWORDS):
            return {"route": "tool_needed"}

        if state.get("image_urls"):
            return {"route": "vision_needed"}

        # ASR 输入倾向直接回答（口语短句通常不需要工具）
        if state.get("input_source") == "asr" and len(user_msg) < 20:
            return {"route": "direct"}

        # LLM 分类
        try:
            result = await self.classifier_llm.ainvoke(
                AVATAR_CLASSIFIER_PROMPT.format(
                    user_message=user_msg,
                    has_attachments="是" if (state.get("file_urls") or state.get("image_urls")) else "否",
                )
            )
            route = result.content.strip().strip('"').strip("'")
            if route not in ("direct", "tool_needed"):
                route = "direct"
        except Exception:
            route = "direct"

        return {"route": route}

    def _route_after_classify(self, state: AvatarState) -> str:
        route = state.get("route", "direct")
        if route == "vision_needed":
            return "vision_needed"
        elif route == "tool_needed":
            return "tool_needed"
        return "direct"

    async def _direct_answer_node(self, state: AvatarState) -> dict:
        """直接回答路径"""
        messages = [SystemMessage(content=state["system_prompt"])] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def _vision_answer_node(self, state: AvatarState) -> dict:
        """视觉回答路径 — 使用 GLM 多模态"""
        messages = state.get("messages") or []
        user_msg = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                user_msg = m.content
                break
        result = await self.vision_service.analyze_images(state.get("image_urls") or [], user_msg)
        text = str(result.get("analysis_text", "")).strip() or "我看完图片了，我们继续。"
        return {"messages": [AIMessage(content=text)]}

    async def _agent_node(self, state: AvatarState) -> dict:
        """工具调用路径"""
        tools = _lazy_import_tools()
        llm_with_tools = self.llm.bind_tools(tools) if tools else self.llm

        from app.shared.request_context import set_user_id, set_session_id
        set_user_id(state["user_id"])
        set_session_id(state["session_id"])

        messages = [SystemMessage(content=state["tool_system_prompt"])] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def _tools_node(self, state: AvatarState) -> dict:
        """执行工具调用"""
        from langchain_core.messages import ToolMessage
        tools = _lazy_import_tools()
        tool_map = {t.name: t for t in tools}

        results = []
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                tool_name = tc["name"]
                tool_fn = tool_map.get(tool_name)
                if tool_fn:
                    try:
                        output = await tool_fn.ainvoke(tc["args"])
                        results.append(
                            ToolMessage(content=str(output), tool_call_id=tc["id"])
                        )
                    except Exception as e:
                        results.append(
                            ToolMessage(content=f"工具执行出错: {e}", tool_call_id=tc["id"])
                        )
        return {"messages": results}

    def _should_use_tools(self, state: AvatarState) -> str:
        """判断是否继续调用工具"""
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return "end"

    # ---- 辅助方法 ----

    @staticmethod
    def _format_chat_ctx(chat_ctx: list) -> str:
        if not chat_ctx:
            return "（无历史对话）"
        lines = []
        for msg in chat_ctx[-10:]:
            role = "学生" if isinstance(msg, HumanMessage) else "教师"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    @staticmethod
    def _build_skills_context() -> str:
        try:
            from app.skills.manager import SkillManager
            sm = SkillManager()
            skills = sm.list_skills()
            if not skills:
                return "暂无可用技能"
            return "\n".join(f"- {s['name']}: {s.get('description', '')}" for s in skills)
        except Exception:
            return "暂无可用技能"

    @staticmethod
    def _build_file_ctx(
        image_urls: list[str] | None,
        file_urls: list[str] | None,
    ) -> str:
        parts = []
        if image_urls:
            parts.append(f"用户上传了 {len(image_urls)} 张图片")
        if file_urls:
            parts.append(f"用户上传了 {len(file_urls)} 个文件")
        return "。".join(parts) if parts else "无附件"
