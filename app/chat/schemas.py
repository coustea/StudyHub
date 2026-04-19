from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TypedDict, Annotated

from pydantic import BaseModel
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# ===================================================================
# API 层数据模型（Pydantic BaseModel）
# ===================================================================

# 聊天请求（当前接口用 Form 接收参数，此类未直接使用）
class MentorChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    image_urls: Optional[list[str]] = None
    file_urls: Optional[list[str]] = None


class AttachmentInfo(BaseModel):
    """单条附件信息。"""
    url: str
    type: str       # "image" | "document"
    name: str


class ToolCallRecord(BaseModel):
    """一次工具调用的完整记录（API 层）。"""
    tool: str        # 工具名称
    args: dict | str
    result: str | dict
    status: str      # "success" | "error"


class ChatMessageItem(BaseModel):
    """返回给前端的消息条目。"""
    role: str  # "user" | "assistant" | "tool"
    content: str
    attachments: Optional[list[AttachmentInfo]] = None
    tool_calls: Optional[list[ToolCallRecord]] = None
    created_at: Optional[datetime] = None


class UploadResponse(BaseModel):
    """文件上传成功响应。"""
    url: str            # 前端访问该文件的 API 路径
    file_type: str      # "image" | "document"
    original_name: str
    size_bytes: int


# ===================================================================
# Agent 内部状态类型（TypedDict，total=False 兼容 LangGraph 增量更新）
# ===================================================================

class PlanStep(TypedDict, total=False):
    """结构化计划步骤，由 planner LLM 生成。"""
    step_index: int                          # 步骤在计划中的序号（0-based）
    kind: str                                # 步骤类型: tool | llm | final_answer
    name: str                                # 工具名或步骤标识（如 "duckduckgo_search"）
    goal: str                                # 步骤目标描述（供 LLM 理解意图）
    args_hint: dict[str, Any]                # 推荐参数（planner 的建议，执行时可被覆盖）


class StepResult(TypedDict, total=False):
    """单步执行结果，记录每一步的成功/失败详情。"""
    plan_version: int                        # 执行时对应的计划版本号
    step_index: int                          # 对应 PlanStep 的序号
    step_kind: str                           # 对应 PlanStep.kind
    step_name: str                           # 对应 PlanStep.name
    goal: str                                # 对应 PlanStep.goal
    args_hint: dict[str, Any]                # 原始推荐参数
    execution_args: dict[str, Any]           # 实际执行参数（可能被修复/补全过）
    success: bool                            # 执行是否成功
    output_summary: str                      # 输出摘要（截断后的工具返回文本）
    output: str                              # 完整输出文本
    failure_reason: str                      # 失败原因（成功时为空）
    error_stack: str                         # 异常堆栈（成功时为空）
    duration_ms: int                         # 执行耗时（毫秒）


class ToolCallDetail(TypedDict, total=False):
    """工具/技能调用记录（Agent 内部状态），持久化到数据库供历史查看。"""
    tool: str                                # 工具名称
    args: dict[str, Any] | str               # 调用参数
    result: str                              # 工具返回结果（截断）
    status: str                              # 调用状态: "success" | "error"
    plan_version: int                        # 所属计划版本
    step_index: int                          # 所属步骤序号
    step_name: str                           # 所属步骤名称
    is_search_fetch: bool                    # 是否属于搜索/抓取类（用于统计）
    query: str                               # 搜索查询关键词（观测用）
    url: str                                 # 抓取目标 URL（观测用）
    error: str                               # 错误信息
    error_stack: str                         # 错误堆栈


class BudgetState(TypedDict, total=False):
    """工具调用统计状态。"""
    total_tool_calls: int                    # 已执行的工具调用总数
    search_fetch_calls: int                  # 已执行的搜索/抓取类调用数


class TutorState(TypedDict, total=False):
    """LangGraph 运行状态，贯穿整个图执行过程。

    total=False 表示所有字段均可选，LangGraph 会对每个节点的返回值
    做增量合并（dict update），而非全量替换。
    """

    # ---- 用户身份与附件 ----
    user_id: int                             # 当前用户 ID
    session_id: str                          # 当前会话 ID（UUID 字符串）
    image_urls: Optional[list[str]]          # 用户上传的图片 URL 列表
    file_urls: Optional[list[str]]           # 用户上传的文件 URL 列表

    # ---- 路由与执行模式 ----
    route: str                               # 分类结果: "direct" | "vision_needed" | "tool_needed"
    execution_mode: str                      # 执行模式: "direct" | "vision" | "plan_execute"

    # ---- 上下文信息（在 _build_* 方法中构建） ----
    profile_context: str                     # 用户画像文本（8维学习偏好）
    fact_context: str                        # 长期记忆事实文本
    recent_chat_context: str                 # 最近 7 天对话上下文
    file_context: str                        # 用户上传文件信息文本
    attachment_analysis_context: str         # 上传后并行预分析结果（图片+文档）
    attachment_analysis: dict[str, Any]      # 结构化并行预分析结果

    # ---- Prompt 模板 ----
    system_prompt: str                       # direct_answer 使用的系统提示词
    tool_system_prompt: str                  # plan-execute 使用的系统提示词（含工具规则）

    # ---- 对话消息 ----
    messages: Annotated[list[AnyMessage], add_messages]  # LangGraph 消息列表，使用 add_messages reducer

    # ---- 计划与执行 ----
    plan: list[PlanStep]                     # 当前执行计划（步骤列表）
    plan_version: int                        # 计划版本号（每次重新规划递增）
    current_step_index: int                  # 当前执行到的步骤序号
    step_results: list[StepResult]           # 所有已完成步骤的结果列表
    last_step_result: StepResult             # 最近一次步骤结果（供守卫判断）

    # ---- 重试与重规划计数 ----
    current_step_retry_count: int            # 当前步骤的修复重试次数
    partial_replan_count: int                # 已执行的局部重规划次数
    full_replan_count: int                   # 已执行的全局重规划次数

    # ---- 终止与调试信息 ----
    last_failure_reason: str                 # 最近一次步骤失败的原因
    last_guard_decision: str                 # 最近一次守卫的决策结果
    guard_reason: str                        # 守卫决策的理由
    termination_reason: str                  # 图执行终止原因

    # ---- 工具调用记录 ----
    budget: BudgetState                      # 工具调用统计状态
    tool_call_records: list[ToolCallDetail]  # 所有工具调用记录（持久化用）
