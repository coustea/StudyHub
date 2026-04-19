import os
import json

import pytest
from langchain_core.messages import AIMessage

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.resource.agents.mindmap.agent import MindmapGenerator


class _FakeMindmapTool:
    def __init__(self, file_path: str, html: str) -> None:
        self.file_path = file_path
        self.html = html
        self.called_with: str | None = None

    def invoke(self, payload: dict[str, str]) -> str:
        self.called_with = payload["markdown_text"]
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(self.html)
        return json.dumps({"file_path": self.file_path, "title": "测试导图"}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_validate_node_recovers_html_from_markdown_only_output(tmp_path, monkeypatch):
    agent = MindmapGenerator()
    html_path = tmp_path / "tcp.html"
    fake_tool = _FakeMindmapTool(str(html_path), "<html><body>mindmap</body></html>")

    import app.resource.agents.mindmap.agent as mindmap_agent_module

    monkeypatch.setattr(mindmap_agent_module, "markdown_to_mindmap", fake_tool)

    state = {
        "messages": [
            AIMessage(
                content="# TCP 三次握手\n- 基本概念\n  - 建立可靠连接\n  - 同步序列号\n- 状态流转\n  - SYN_SENT\n  - SYN_RCVD\n- 常见误区\n  - 误以为两次握手足够\n  - 忽略半连接问题"
            )
        ],
        "retry_count": 0,
    }

    result = await agent._validate_node(state)

    assert result["is_valid"] is True
    assert result["file_path"] == str(html_path)
    assert result["html_content"] == "<html><body>mindmap</body></html>"
    assert result["markdown_content"].startswith("# TCP 三次握手")
    assert result["node_count"] >= 8
    assert fake_tool.called_with is not None


@pytest.mark.asyncio
async def test_validate_node_rejects_sparse_markdown_output(monkeypatch):
    agent = MindmapGenerator()

    import app.resource.agents.mindmap.agent as mindmap_agent_module

    class _ExplodingTool:
        def invoke(self, payload: dict[str, str]) -> str:
            raise AssertionError("tool should not be called for sparse markdown")

    monkeypatch.setattr(mindmap_agent_module, "markdown_to_mindmap", _ExplodingTool())

    state = {
        "messages": [
            AIMessage(
                content="# TCP\n- 基本概念"
            )
        ],
        "retry_count": 0,
    }

    result = await agent._validate_node(state)

    assert result["is_valid"] is False
    assert "导图结构" in result["validation_feedback"]
    assert result["node_count"] < 8
