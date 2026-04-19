import json
import os

import pytest
from langchain_core.messages import AIMessage

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.resource.agents.ppt.agent import (  # noqa: E402
    PptAgent,
    _check_outline_quality,
    _select_ppt_style,
)


class _FakePptTool:
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.called_payload: dict | None = None

    def invoke(self, payload: dict) -> str:
        self.called_payload = payload
        with open(self.file_path, "wb") as f:
            f.write(b"pptx")
        return json.dumps(
            {
                "file_path": self.file_path,
                "slide_count": 7,
                "slide_titles": ["封面", "引入问题", "核心概念", "机制流程", "盲区攻克", "总结回顾", "延伸思考"],
            },
            ensure_ascii=False,
        )


def test_select_ppt_style_uses_cognitive_style_keywords():
    assert _select_ppt_style("视觉型学习者") == "creative_bold"
    assert _select_ppt_style("偏逻辑顺序推进") == "corporate_blue"
    assert _select_ppt_style("喜欢整体把握全局") == "nature_green"


def test_check_outline_quality_rejects_sparse_outline():
    ok, feedback, slide_count = _check_outline_quality(
        "# TCP 三次握手\n\n## 核心概念\n- 连接建立"
    )

    assert ok is False
    assert "页数" in feedback or "备注" in feedback
    assert slide_count == 1


@pytest.mark.asyncio
async def test_validate_node_recovers_ppt_file_from_outline_only_output(tmp_path, monkeypatch):
    agent = PptAgent()
    ppt_path = tmp_path / "tcp.pptx"
    fake_tool = _FakePptTool(str(ppt_path))

    import app.resource.agents.ppt.agent as ppt_agent_module

    monkeypatch.setattr(ppt_agent_module, "save_ppt_file", fake_tool)

    state = {
        "topic": "TCP 三次握手",
        "style": "creative_bold",
        "messages": [
            AIMessage(
                content=(
                    "# TCP 三次握手教学演示\n\n"
                    "## 引入问题\n"
                    "> 为什么 TCP 不能只用两次握手？\n"
                    "[note]\n从丢失确认和历史连接污染引入课堂问题。\n[/note]\n\n"
                    "## 核心概念\n"
                    "- TCP 通过三次握手同步双方的初始序列号并确认收发能力。\n"
                    "[note]\n解释 SYN 和 ACK 的角色。\n[/note]\n\n"
                    "## 状态流转\n"
                    "1. 客户端发送 SYN 建立首次连接意图。\n"
                    "2. 服务端返回 SYN+ACK 确认并同步自己的序列号。\n"
                    "3. 客户端发送 ACK，连接正式进入 ESTABLISHED。\n"
                    "[note]\n逐步讲状态转换和报文含义。\n[/note]\n\n"
                    "## 盲区攻克\n"
                    "- 两次握手无法避免失效连接请求重新抵达带来的资源浪费。\n"
                    "[note]\n结合半连接队列说明真实风险。\n[/note]\n\n"
                    "## 总结回顾\n"
                    "- 三次握手的本质是同步序列号、确认收发能力、避免历史报文干扰。\n"
                    "[note]\n用一句口诀帮助记忆。\n[/note]\n\n"
                    "## 延伸思考\n"
                    "- 如果最后一次 ACK 丢失，服务端会如何处理？\n"
                    "[note]\n引导学生思考超时重传与四次挥手的联系。\n[/note]\n"
                )
            )
        ],
        "retry_count": 0,
    }

    result = await agent._validate_node(state)

    assert result["is_valid"] is True
    assert result["file_path"] == str(ppt_path)
    assert result["slide_count"] == 7
    assert result["outline_markdown"].startswith("# TCP 三次握手教学演示")
    assert result["slide_titles"][-1] == "延伸思考"
    assert fake_tool.called_payload is not None
    assert fake_tool.called_payload["style"] == "creative_bold"
