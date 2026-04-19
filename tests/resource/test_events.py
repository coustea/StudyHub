import asyncio
import json

import pytest

from app.resource.events import AgentEventEmitter


@pytest.mark.asyncio
async def test_emitter_streams_structured_workflow_and_agent_events():
    emitter = AgentEventEmitter()

    await emitter.emit_workflow("planning", "正在规划资源包")
    await emitter.emit_agent_status("content", "running", "正在生成精讲文档")
    await emitter.emit_artifact_ready(
        "content",
        {
            "success": True,
            "type": "doc",
            "title": "TCP 三次握手精讲",
        },
    )
    await emitter.emit_done("资源包构建完成")

    chunks = []
    async for chunk in emitter.stream():
        chunks.append(chunk)

    payloads = [
        json.loads(item.removeprefix("data: ").strip())
        for item in chunks
    ]

    assert [item["type"] for item in payloads] == [
        "workflow",
        "agent_status",
        "artifact_ready",
        "done",
    ]
    assert payloads[0]["stage"] == "planning"
    assert payloads[1]["agent"] == "content"
    assert payloads[2]["artifact"]["title"] == "TCP 三次握手精讲"
