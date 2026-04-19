"""ToolMessage 内容清理工具。"""

from langchain_core.messages import AnyMessage, ToolMessage


def sanitize_tool_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """将 ToolMessage 中的 list 类型 content 转为纯文本，确保 API 兼容。"""
    safe_messages: list[AnyMessage] = []
    for msg in messages:
        if getattr(msg, "type", "") == "tool" and isinstance(msg.content, list):
            texts: list[str] = []
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                else:
                    texts.append(str(block))
            safe_messages.append(
                ToolMessage(
                    content="\n".join(texts),
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    status=getattr(msg, "status", "success"),
                )
            )
        else:
            safe_messages.append(msg)
    return safe_messages
