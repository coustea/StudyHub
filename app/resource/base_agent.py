"""
基础资源 Agent 类。
提供统一的 LangGraph 工作流、工具加载、重试机制和三层记忆结构（情景、长效、黑板）。

每个 Agent 只需提供：
  - prompt.md       → 系统提示词模板
  - agent.py        → 子类实现，声明 tool_names / skill_names
工具和技能从 app/tools/ 和 app/skills/ 统一按名加载。
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypedDict, Optional, Annotated

from app.infra.llm import get_llm, get_spark_x_llm
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AnyMessage
from langchain_core.tools import BaseTool
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from app.infra.logging import get_logger
from app.config import MAX_MESSAGE_HISTORY, LLM_TIMEOUT
from app.shared.paths import WORKPLACE_DIR

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────
# 常量定义
# ──────────────────────────────────────────────────────────────


class BlackboardKeys:
    """黑板共享内存的标准键名常量"""
    CONTENT = "content"
    MINDMAP = "mindmap"
    CODE = "code"
    QUIZ = "quiz"
    READING = "reading"
    IMAGE = "image"
    VIDEO = "video"
    PPT = "ppt"

    @classmethod
    def all_keys(cls) -> list[str]:
        """获取所有标准键名"""
        return [cls.CONTENT, cls.MINDMAP, cls.CODE, cls.QUIZ, cls.READING, cls.IMAGE, cls.VIDEO, cls.PPT]


# ──────────────────────────────────────────────────────────────
# State 定义
# ──────────────────────────────────────────────────────────────


class BaseAgentState(TypedDict, total=False):
    """基础 Agent 状态字典，包含三层记忆架构。子类可继承此字典扩展内部字段。

    字段语义说明：
      - major:    学生所属专业（上下文，可为空）
      - course:   当前课程名称
      - topic:    请求详细知识点（如"二叉树遍历算法"），应比 gap 更具体
      - gap:      学生的知识短板描述（如"不理解递归"）
      - user_profile: 用户画像字典，来自长效记忆
      - shared_memory: 前置 Agent 输出的黑板共享上下文
    """
    # 1. 任务级情景记忆 (Episodic Memory)
    major: str
    course: str
    topic: str   # 知识点（具体请求对象）
    gap: str     # 学生知识短板

    # 2. 全局长效记忆 (Long-Term Memory)
    user_profile: dict[str, Any]

    # 3. 智能体间共享黑板 (Shared Blackboard)
    shared_memory: dict[str, Any]

    # 4. 执行与控制状态
    messages: Annotated[list[AnyMessage], add_messages]
    is_valid: bool
    validation_feedback: str
    retry_count: int
    max_retries: int
    error: Optional[str]


# ──────────────────────────────────────────────────────────────
# BaseResourceAgent
# ──────────────────────────────────────────────────────────────


class BaseResourceAgent(ABC):
    """资源生成 Agent 基类。

    Agent 通过声明 tool_names 和 skill_names 来获取所需的工具和技能，
    运行时从 app/tools/registry 和 app/skills/manager 统一加载。
    """

    # 子类覆盖这两个列表来声明依赖
    tool_names: list[str] = []
    skill_names: list[str] = []

    force_json_mode: bool = False

    def __init__(
        self,
        name: str,
        agent_dir: Path,
        state_schema: type = BaseAgentState,
        temperature: float = 0.3,
    ):
        """初始化 Agent，配置 LLM 及并发锁。"""
        self.name = name
        self.agent_dir = agent_dir
        self.state_schema = state_schema

        # 初始化 LLM 实例（复用缓存）
        self.llm = get_spark_x_llm(temperature=temperature) # 使用Spark X避免达到并发限制
        self.graph = None
        self._tools: list[BaseTool] | None = None

        # P5：应对并发初始化竞态，确保 graph 唯一
        self._init_lock = asyncio.Lock()

        # 加载 prompt 模板
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """从 agent_dir/prompt.md 加载提示词模板。"""
        prompt_path = self.agent_dir / "prompt.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"[{self.name}] prompt 文件不存在: {prompt_path}")
        content = prompt_path.read_text(encoding="utf-8")
        logger.info(f"[{self.name}] 加载 prompt: {prompt_path}")
        return content

    # ══════════════════════════════════════════════════════════
    # 工具加载（从统一注册表 + 技能管理器）
    # ══════════════════════════════════════════════════════════

    async def _load_tools(self) -> None:
        """从 registry 按 tool_names 加载工具，从 SkillManager 按 skill_names 加载技能。"""
        from app.tools import registry
        from app.skills.manager import SkillManager

        # 1. 触发所有工具模块的自注册（import 触发模块级 register 调用）
        _ensure_tools_loaded()

        # 2. 从 registry 获取声明的工具
        registered_tools = []
        if self.tool_names:
            registered_tools = registry.get_many(self.tool_names)

        # 3. 从 SkillManager 获取技能工具
        #    skill_names 为空 → 加载全部技能（LLM 自主选择）
        #    skill_names 非空 → 作为白名单过滤
        skill_tools = []
        sm = SkillManager()
        await sm.load_all()
        skill_tools = await sm.get_tools(self.skill_names or None)

        self._tools = registered_tools + skill_tools
        logger.info(
            f"[{self.name}] 共加载 {len(self._tools)} 个工具: "
            f"{[t.name for t in self._tools]}"
        )

    # ══════════════════════════════════════════════════════════
    # 图构建（LangGraph StateGraph）
    # ══════════════════════════════════════════════════════════

    async def _ensure_graph(self):
        """P5：协程安全的图构建入口（double-check + asyncio.Lock）。"""
        if self.graph is not None:
            return
        async with self._init_lock:
            if self.graph is not None:  # double-check
                return
            await self._load_tools()
            self.graph = await self._build_graph()
            logger.info(f"[{self.name}] LangGraph 工作流构建完成")

    async def _build_graph(self):
        """P1：构建默认图拓扑（生成 → 工具 → 校验 → 重试）。"""
        graph = StateGraph(self.state_schema)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_node("validate", self._validate_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._custom_tools_condition)
        graph.add_edge("tools", "agent")
        graph.add_conditional_edges(
            "validate",
            self._should_retry,
            path_map={"end": END, "retry": "agent"},
        )
        return graph.compile()

    def _custom_tools_condition(self, state: Any) -> str:
        """判断 LLM 是否发起了工具调用请求。"""
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "tools"
        return "validate"

    def _should_retry(self, state: Any) -> str:
        """控制重试逻辑。"""
        if state.get("error"):
            return "end"
        if state.get("is_valid", False):
            return "end"
        if state.get("retry_count", 0) < state.get("max_retries", 2):
            return "retry"
        return "end"

    # ══════════════════════════════════════════════════════════
    # 抽象方法（子类必须实现）
    # ══════════════════════════════════════════════════════════

    @abstractmethod
    def _build_system_message(self, state: Any) -> str:
        """子类必须实现：构建系统提示词。"""
        ...

    @abstractmethod
    def _build_initial_human_message(self, state: Any) -> str:
        """子类必须实现：构建用户请求消息。"""
        ...

    @abstractmethod
    async def _validate_node(self, state: Any) -> dict:
        """子类必须实现：校验节点逻辑。"""
        ...

    # ══════════════════════════════════════════════════════════
    # 公共节点实现
    # ══════════════════════════════════════════════════════════

    def _truncate_messages(
        self,
        messages: list[AnyMessage],
        keep_last_n: int = 40,
    ) -> list[AnyMessage]:
        """截断消息历史，保留系统消息和最近 N 条对话。"""
        if len(messages) <= keep_last_n + 1:
            return messages

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(non_system) <= keep_last_n:
            return messages

        truncated = system_msgs + non_system[-keep_last_n:]
        logger.info(
            f"[{self.name}] 消息截断: {len(messages)} → {len(truncated)} 条"
        )
        return truncated

    async def _agent_node(self, state: Any) -> dict:
        """LLM 调用节点（模板方法）。

        调用链：_build_llm_messages → _prepare_llm_messages → _invoke_llm → _postprocess_response

        子类可覆写整个方法，也可只覆写某个子步骤。
        """
        try:
            new_messages: list = []
            llm_messages = self._build_llm_messages(state, new_messages)
            llm_messages = self._prepare_llm_messages(llm_messages, state)

            result = await self._invoke_llm(llm_messages, state)
            if isinstance(result, dict):
                return result  # _invoke_llm 返回错误 dict，直接透传

            return self._postprocess_response(result, new_messages, state)
        except Exception as e:
            logger.error(f"[{self.name}] LLM 接口调用异常: {e}")
            return {"error": str(e), "is_valid": False}

    def _build_llm_messages(self, state: Any, new_messages: list) -> list:
        """构建发送给 LLM 的消息列表。

        new_messages 列表由本方法填充，用于追踪本次新增的消息（不含已有历史）。
        子类可覆写以自定义消息构建逻辑（如分步生成）。
        """
        existing_messages = state.get("messages", [])
        retry_count = state.get("retry_count", 0)
        feedback = state.get("validation_feedback", "")

        if not existing_messages:
            sys_content = self._build_system_message(state)
            human_content = self._build_initial_human_message(state)
            new_messages.extend([
                SystemMessage(content=str(sys_content)),
                HumanMessage(content=str(human_content)),
            ])
            return list(new_messages)

        if retry_count > 0 and feedback:
            last_msg_content = existing_messages[-1].content if existing_messages else ""
            if not isinstance(last_msg_content, str) or "上一次生成未通过校验" not in last_msg_content:
                new_messages.append(HumanMessage(
                    content=f"上一次生成未通过校验，原因：{feedback}\n请根据上述反馈修正后重新生成。"
                ))

        return list(existing_messages) + new_messages

    def _prepare_llm_messages(self, messages: list, state: Any) -> list:
        """截断与清洗消息（子类一般不需要覆写）。"""
        messages = self._truncate_messages(messages, keep_last_n=MAX_MESSAGE_HISTORY)
        from app.shared.sanitizers import sanitize_tool_messages
        return sanitize_tool_messages(messages)

    async def _invoke_llm(self, messages: list, state: Any) -> AIMessage | dict:
        """调用 LLM，处理工具绑定、JSON Mode、超时和异常。

        返回 AIMessage（成功）或 dict（错误，含 error + is_valid 字段）。
        子类可覆写以自定义 LLM 调用（如使用不同的模型、温度、工具绑定策略）。
        """
        llm_plain = self.llm.bind_tools(self._tools) if self._tools else self.llm
        llm_with_tools = llm_plain
        if self.force_json_mode:
            try:
                llm_with_tools = llm_plain.bind(response_format={"type": "json_object"})
            except Exception as exc:
                logger.warning(f"[{self.name}] JSON Mode bind 失败，fallback=plain: {exc}")
                llm_with_tools = llm_plain

        llm_timeout = LLM_TIMEOUT
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(messages),
                timeout=llm_timeout,
            )
            return response
        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] LLM 调用超时")
            return {"error": "LLM 调用超时", "is_valid": False}
        except Exception as exc:
            if self.force_json_mode:
                logger.warning(f"[{self.name}] JSON Mode 调用失败，retry=plain: {exc}")
                try:
                    response = await asyncio.wait_for(
                        llm_plain.ainvoke(messages),
                        timeout=llm_timeout,
                    )
                    return response
                except Exception:
                    raise
            raise

    def _postprocess_response(self, response: AIMessage, new_messages: list, state: Any) -> dict:
        """后处理 LLM 响应（JSON→tool_call 补丁）并返回状态更新 dict。"""
        # 文本补丁：模型输出 JSON 工具调用但没走 tool_calls 通道时，手动补上
        if isinstance(response, AIMessage) and not response.tool_calls and self._tools:
            content = response.content.strip()
            if (content.startswith("```json") and content.endswith("```")) or (content.startswith("{") and content.endswith("}")):
                try:
                    json_str = content[7:-3].strip() if content.startswith("```json") else content
                    data = json.loads(json_str)
                    if isinstance(data, dict) and "name" in data:
                        response.tool_calls = [{
                            "name": data["name"],
                            "args": data.get("arguments", data.get("args", {})),
                            "id": f"call_{int(time.time())}",
                            "type": "tool_call"
                        }]
                except Exception:
                    pass

        return {"messages": new_messages + [response]}

    # ══════════════════════════════════════════════════════════
    # 记忆层辅助方法
    # ══════════════════════════════════════════════════════════

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        """从黑板共享内存中提取协作上下文（子类可重写）。"""
        return ""

    def _format_user_profile(self, profile: dict[str, Any]) -> str:
        """将用户画像格式化为 Prompt 指令。"""
        if not profile:
            return ""
        parts = [f"- {k}: {v}" for k, v in profile.items() if v]
        return "\n".join(parts) if parts else ""

    def _append_context_to_prompt(self, system_prompt: str, state: Any) -> str:
        """三层记忆注入逻辑。"""
        profile = state.get("user_profile", {})
        profile_str = self._format_user_profile(profile)
        if profile_str:
            system_prompt += f"\n\n## [学习者画像 (Long-Term Memory)]\n{profile_str}"

        shared_memory = state.get("shared_memory", {})
        memory_ctx = self._extract_memory(shared_memory)
        if memory_ctx:
            system_prompt += f"\n\n## [协作上下文 (Shared Memory)]\n{memory_ctx}"

        kb_context = state.get("knowledge_base_context", "")
        if kb_context:
            system_prompt += f"\n\n## [知识库参考]\n{kb_context}"

        return system_prompt

    @staticmethod
    def format_blackboard_summary(shared_memory: dict[str, Any]) -> str:
        """格式化黑板共享内存为可读摘要。"""
        if not shared_memory:
            return "（暂无前置资源）"

        summary_parts = []
        for key, value in shared_memory.items():
            if isinstance(value, dict) and value.get("success"):
                summary_parts.append(f"- {value.get('type', key)}: {value.get('file_path', str(len(str(value.get('content', '')))) + ' 字')}")
        return "\n".join(summary_parts) if summary_parts else "（暂无可用资源）"


# ──────────────────────────────────────────────────────────────
# 工具模块懒加载
# ──────────────────────────────────────────────────────────────

_tools_loaded = False


def _ensure_tools_loaded() -> None:
    """确保所有工具模块已被 import，触发模块级的 register() 调用。"""
    global _tools_loaded
    if _tools_loaded:
        return

    import importlib
    _tool_modules = [
        "app.tools.file_operator",
        "app.tools.shell_executor",
        "app.tools.code_runner",
        "app.tools.markdown_to_mindmap",
        "app.tools.web_fetcher",
        "app.tools.duckduckgo_search",
        "app.tools.document_executor",
    ]
    for mod_name in _tool_modules:
        try:
            importlib.import_module(mod_name)
        except Exception as exc:
            logger.warning("[BaseResourceAgent] 工具模块加载失败 %s: %s", mod_name, exc)
    _tools_loaded = True
