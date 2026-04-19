"""
资源 Agent 通用校验工具。

提供跨 Agent 的共享校验辅助函数：
- parse_first_json_value: 从 LLM 响应中解析 JSON（不使用正则）
- extract_last_ai_content: 提取最后一条 AI 消息内容
- make_validation_result: 构建标准校验返回字典
- validate_json_response: JSON + Pydantic 统一校验流程
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage

from app.shared.json_utils import parse_first_json_value


def extract_last_ai_content(
    messages: list[AnyMessage],
    skip_tool_calls: bool = False,
) -> str:
    """提取消息列表中最后一条 AI 消息的文本内容。

    Args:
        messages: LangChain 消息列表
        skip_tool_calls: 是否跳过包含 tool_calls 的 AI 消息

    Returns:
        最后一条 AI 消息的内容字符串，未找到返回空字符串
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if skip_tool_calls and msg.tool_calls:
                # 某些 Agent 会先返回带工具调用的 AIMessage，这里允许调用方跳过它们。
                continue
            content = msg.content
            return content.strip() if isinstance(content, str) else str(content).strip()
    return ""


def make_validation_result(
    is_valid: bool,
    retry_count: int,
    feedback: str = "",
    **fields: Any,
) -> dict[str, Any]:
    """构建标准的校验结果字典。

    Args:
        is_valid: 是否通过校验
        retry_count: 当前重试次数（自动 +1）
        feedback: 校验反馈信息
        **fields: 附加字段（如 questions_json、parsed_questions 等）

    Returns:
        适合从 _validate_node 返回的字典
    """
    # 统一返回结构，避免每个 Agent 的 validate 节点手写一套字段。
    result: dict[str, Any] = {
        "is_valid": is_valid,
        "validation_feedback": feedback,
        "retry_count": retry_count + 1,
    }
    result.update(fields)
    return result


def validate_json_response(
    raw: str,
    pydantic_model: type,
    retry_count: int,
    error_prefix: str = "响应结构",
) -> tuple[bool, str, Any, dict[str, Any]]:
    """JSON + Pydantic 模型统一校验流程。

    典型调用：
        is_valid, feedback, validated, extra = validate_json_response(
            raw, QuizOutput, retry_count, "题目结构"
        )
        if not is_valid:
            return {**extra, "questions_json": raw, "parsed_questions": []}

    Args:
        raw: LLM 原始响应文本
        pydantic_model: Pydantic 模型类（如 QuizOutput、ReadingOutput）
        retry_count: 当前重试次数
        error_prefix: 错误消息前缀

    Returns:
        (is_valid, feedback, validated_instance, extra_dict)
        - is_valid: 是否通过校验
        - feedback: 错误反馈（通过时为空字符串）
        - validated_instance: Pydantic 模型实例（失败时为 None）
        - extra_dict: 校验失败时的标准返回字典（通过时为空字典）
    """
    if not raw:
        feedback = "未生成内容"
        return False, feedback, None, make_validation_result(False, retry_count, feedback)

    try:
        # 不使用正则剥离 fenced code block；由 parse_first_json_value 负责兼容常见输出形态。
        data = parse_first_json_value(raw)
    except Exception as e:
        feedback = f"JSON 解析失败: {e}。请确保输出合法 JSON。"
        return False, feedback, None, make_validation_result(False, retry_count, feedback)

    try:
        # 让 Pydantic 负责字段级结构校验，避免 Agent 各自重复写 schema 判断。
        validated = pydantic_model.model_validate(data)
    except Exception as e:
        feedback = f"{error_prefix}不合法: {e}"
        return False, feedback, None, make_validation_result(False, retry_count, feedback)

    return True, "", validated, {}
