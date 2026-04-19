"""
SSE 事件发射器：以结构化事件把多智能体工作流实时推送给前端。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from app.infra.logging import get_logger

logger = get_logger(__name__)
DEFAULT_QUEUE_SIZE = 200


class AgentEventEmitter:
    def __init__(self):
        # 所有 SSE 事件先入队，路由层只负责把队列转成流式输出。
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=DEFAULT_QUEUE_SIZE)
        logger.info("[Emitter] SSE 事件发射器已创建")

    async def emit(self, event_type: str, **kwargs) -> None:
        payload = {"type": event_type, **kwargs}
        logger.info("[Emitter] 推送事件: type=%s keys=%s", event_type, list(payload.keys()))
        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                logger.warning("[Emitter] 事件队列已满，丢弃最旧事件: type=%s", dropped.get("type") if isinstance(dropped, dict) else "unknown")
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(payload)

    async def emit_workflow(self, stage: str, message: str, **meta: Any) -> None:
        # workflow 事件描述全局阶段，比如 profile_loading / planning / persisting。
        await self.emit("workflow", stage=stage, message=message, meta=meta or {})

    async def emit_agent_status(
        self,
        agent: str,
        status: str,
        message: str,
        **meta: Any,
    ) -> None:
        # agent_status 用于驱动前端状态面板里的 queued/running/success/failed。
        await self.emit("agent_status", agent=agent, status=status, message=message, meta=meta or {})

    async def emit_agent_log(self, agent: str, log: str, **meta: Any) -> None:
        # agent_log 不改变状态，只补充过程说明，适合 terminal 面板展示。
        await self.emit("agent_log", agent=agent, log=log, meta=meta or {})

    async def emit_artifact_ready(self, agent: str, artifact: dict[str, Any]) -> None:
        # artifact_ready 表示前端已经可以开始展示资源，不必等所有 Agent 都完成。
        await self.emit("artifact_ready", agent=agent, artifact=artifact)

    async def emit_bundle_update(
        self,
        completed: int,
        total: int,
        core_ready: bool,
        latest_agent: str | None = None,
        **meta: Any,
    ) -> None:
        await self.emit(
            "bundle_update",
            completed=completed,
            total=total,
            core_ready=core_ready,
            latest_agent=latest_agent,
            meta=meta or {},
        )

    async def emit_done(self, message: str = "资源包构建完成") -> None:
        await self.emit("done", message=message)

    async def stream(self) -> AsyncGenerator[str, None]:
        logger.info("[Emitter] SSE 流开始消费事件")
        while True:
            event = await self._queue.get()
            if event is None:
                logger.info("[Emitter] 收到终止信号，结束 SSE 流")
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") == "done":
                logger.info("[Emitter] 收到 done 事件，结束 SSE 流")
                break
