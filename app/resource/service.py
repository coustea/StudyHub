"""
Resource service — 资源生成全流程：持久化 + 编排 + SSE 推送。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infra.models import GeneratedResource
from app.infra.logging import get_logger
from app.resource.coordinator import CoordinatorAgent, get_agent_registry
from app.resource.events import AgentEventEmitter

logger = get_logger(__name__)


class ResourceService:
    """GeneratedResource 持久化 CRUD。"""

    async def list_user_resources(
        self,
        session: AsyncSession,
        user_id: int,
        limit: int = 20,
    ) -> list[GeneratedResource]:
        # 资源历史按创建时间倒序返回，方便前端先展示最近生成结果。
        stmt = (
            select(GeneratedResource)
            .where(GeneratedResource.user_id == user_id)
            .order_by(GeneratedResource.created_at.desc())
            .limit(limit)
        )
        result = await session.exec(stmt)
        return list(result.all())

    async def get_user_resource(
        self,
        session: AsyncSession,
        user_id: int,
        resource_id: int,
    ) -> GeneratedResource | None:
        resource = await session.get(GeneratedResource, resource_id)
        if resource is None or resource.user_id != user_id:
            return None
        return resource


class ResourceGenerationRuntime:
    """资源生成运行时：DAG 编排 + SSE 推送。"""

    def list_agents(self) -> list[dict]:
        # 前端工作看板需要这份注册表来渲染 agent 名称、角色和类型。
        registry = get_agent_registry()
        return [
            {"id": name, "role": info.role, "desc": info.desc, "type": info.type}
            for name, info in registry.items()
        ]

    async def stream_bundle(
        self,
        *,
        user_id: int,
        task: dict,
        selected_resources: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        logger.info(
            "[ResourceRuntime] 开始流式生成: user_id=%s course=%r selected_resources=%s",
            user_id,
            task.get("course", ""),
            selected_resources,
        )
        emitter = AgentEventEmitter()
        coordinator = CoordinatorAgent(emitter)

        async def run_and_cleanup() -> None:
            try:
                await coordinator.run(
                    user_id=user_id,
                    task=task,
                    selected_resources=selected_resources,
                )
            except Exception as exc:
                logger.error("[ResourceRuntime] 协调器执行异常: %s", exc, exc_info=exc)
                await emitter.emit_agent_status("system", "failed", str(exc))
                await emitter.emit_done("资源生成异常终止")
            finally:
                logger.info("[ResourceRuntime] 开始执行插件清理")
                await self._cleanup_plugins()

        runner = asyncio.create_task(run_and_cleanup())
        try:
            async for chunk in emitter.stream():
                yield chunk
        finally:
            logger.info("[ResourceRuntime] 等待后台协调任务收尾")
            await runner
            logger.info("[ResourceRuntime] 流式生成结束: user_id=%s", user_id)

    async def _cleanup_plugins(self) -> None:
        # 工具和技能现在通过 registry 和 SkillManager 管理，无需清理
        logger.info("[ResourceRuntime] 资源清理完成（统一注册表模式，无需关闭插件连接）")

    async def aclose(self) -> None:
        # 预留给应用退出或测试 teardown 使用，统一回收插件资源。
        await self._cleanup_plugins()


class ResourceUseCases:
    """资源相关用例。"""

    def __init__(self, resource_svc: ResourceService, runtime: ResourceGenerationRuntime) -> None:
        # use case 层只做转发，保持 API 层不直接依赖 runtime 实现细节。
        self.resource_svc = resource_svc
        self.runtime = runtime

    async def stream_bundle(
        self,
        *,
        user_id: int,
        task: dict,
        selected_resources: list[str] | None = None,
    ):
        async for chunk in self.runtime.stream_bundle(
            user_id=user_id,
            task=task,
            selected_resources=selected_resources,
        ):
            yield chunk

    def list_agents(self) -> list[dict]:
        return self.runtime.list_agents()

    async def list_resources(self, session: AsyncSession, user_id: int, limit: int = 20):
        return await self.resource_svc.list_user_resources(session, user_id, limit)

    async def get_resource(self, session: AsyncSession, user_id: int, resource_id: int):
        return await self.resource_svc.get_user_resource(session, user_id, resource_id)


# 模块级单例
resource_service = ResourceService()
resource_runtime = ResourceGenerationRuntime()
resource_usecases = ResourceUseCases(resource_service, resource_runtime)
