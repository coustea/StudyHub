"""
Coordinator Agent：画像加载 + 任务规划 + 分阶段编排 + SSE 实时推送。
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from app.infra.llm import get_deepseek_reasoner_llm

from app.config import DEEPSEEK_REASONER_MODEL
from app.infra.database import engine
from app.infra.logging import get_logger
from app.resource.events import AgentEventEmitter
from app.resource.exceptions import PlanningError
from app.resource.planning import (
    build_default_resource_plan,
    iter_plan_phases,
    merge_planned_tasks_into_plan,
)
from app.resource.profile_snapshot import ProfileSnapshotLoader
from app.resource.schemas import LearnerProfileSnapshot, PersonalizedTaskContext, ResourcePlan

logger = get_logger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"
PLANNER_PROMPT_PATH = PROMPT_DIR / "planner.md"


@dataclass
class AgentEntry:
    role: str
    desc: str
    type: str
    stage: str
    agent_loader: Callable[[], Any]
    method: str
    result_summary: Callable[[dict], str] = field(default=lambda r: "")
    extra_kwargs: dict = field(default_factory=dict)


def _load_agent(module_path: str, attr_name: str) -> Callable[[], Any]:
    def _loader() -> Any:
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)

    return _loader


def build_agent_registry() -> dict[str, AgentEntry]:
    return {
    "content": AgentEntry(
        role="Content Agent",
        desc="撰写深度知识精讲",
        type="doc",
        stage="core",
        agent_loader=_load_agent("app.resource.agents.content", "content_writer"),
        method="generate_content",
        result_summary=lambda r: f"文档 {len(r.get('content', ''))} 字",
    ),
    "mindmap": AgentEntry(
        role="Mindmap Agent",
        desc="构建核心知识拓扑图",
        type="mindmap",
        stage="core",
        agent_loader=_load_agent("app.resource.agents.mindmap", "mindmap_generator"),
        method="generate_mindmap",
        result_summary=lambda r: f"导图已生成 → {r.get('file_path') or '内存结果'}",
    ),
    "quiz": AgentEntry(
        role="Quiz Agent",
        desc="生成分层练习题库",
        type="quiz",
        stage="core",
        agent_loader=_load_agent("app.resource.agents.quiz", "quiz_agent"),
        method="generate_quiz",
        result_summary=lambda r: f"共 {len(r.get('questions', []))} 道题",
    ),
    "reading": AgentEntry(
        role="Reading Agent",
        desc="检索拓展阅读与论文",
        type="reading",
        stage="enhancement",
        agent_loader=_load_agent("app.resource.agents.reading", "reading_agent"),
        method="generate_reading",
        result_summary=lambda r: f"共 {len(r.get('recommendations', []))} 条推荐",
    ),
    "code": AgentEntry(
        role="Code Agent",
        desc="编写可运行实操案例",
        type="code",
        stage="enhancement",
        agent_loader=_load_agent("app.resource.agents.code", "code_agent"),
        method="generate_code",
        result_summary=lambda r: f"语言: {r.get('detected_language', 'unknown')}",
    ),
    "image": AgentEntry(
        role="Image Agent",
        desc="生成教学配图与图解资源",
        type="image",
        stage="enhancement",
        agent_loader=_load_agent("app.resource.agents.image", "image_agent"),
        method="generate_image",
        result_summary=lambda r: f"生成 {len(r.get('images', []))} 张图解",
    ),
    "ppt": AgentEntry(
        role="PPT Agent",
        desc="生成演示文稿与讲稿",
        type="ppt",
        stage="presentation",
        agent_loader=_load_agent("app.resource.agents.ppt", "ppt_agent"),
        method="generate_ppt",
        result_summary=lambda r: "PPT 大纲已生成",
    ),
    "video": AgentEntry(
        role="Video Agent",
        desc="生成视频讲解脚本与分镜",
        type="video",
        stage="presentation",
        agent_loader=_load_agent("app.resource.agents.video", "video_agent"),
        method="generate_video",
        result_summary=lambda r: f"分镜 {len(r.get('storyboard', []))} 幕",
    ),
}


AGENT_REGISTRY: dict[str, AgentEntry] | None = None


def get_agent_registry() -> dict[str, AgentEntry]:
    global AGENT_REGISTRY
    if AGENT_REGISTRY is None:
        AGENT_REGISTRY = build_agent_registry()
    return AGENT_REGISTRY


class CoordinatorAgent:
    def __init__(
        self,
        emitter: AgentEventEmitter,
        profile_loader: ProfileSnapshotLoader | None = None,
    ):
        self.emitter = emitter
        self.profile_loader = profile_loader or ProfileSnapshotLoader()
        self.llm = get_deepseek_reasoner_llm(streaming=False)
        logger.info("[Coordinator] 初始化完成: planner_model=%s", DEEPSEEK_REASONER_MODEL)

    async def run(
        self,
        user_id: int,
        task: dict,
        selected_resources: list[str] | None = None,
    ) -> dict:
        logger.info(
            "[Coordinator] 开始执行资源生成: user_id=%s course=%r need=%r selected_resources=%s",
            user_id,
            task.get("course", ""),
            task.get("need", "review"),
            selected_resources,
        )
        await self.emitter.emit_workflow("profile_loading", "正在读取学习者画像...")
        snapshot = await self._safe_load_profile(user_id)
        personalized_context = self.profile_loader.build_personalized_context(snapshot, task)
        logger.info(
            "[Coordinator] 个性化上下文已生成: difficulty=%s styles=%s emphasis_count=%s",
            personalized_context.target_difficulty,
            personalized_context.explanation_style,
            len(personalized_context.emphasis),
        )

        allowed_agents = self._normalize_selected_resources(selected_resources)
        logger.info("[Coordinator] 归一化资源范围: %s", allowed_agents or "ALL")
        await self.emitter.emit_workflow("planning", "正在生成个性化资源计划...")
        resource_plan = await self._safe_build_plan(
            task=task,
            snapshot=snapshot,
            personalized_context=personalized_context,
            allowed_agents=allowed_agents,
        )
        logger.info(
            "[Coordinator] 资源计划已确定: core=%s enhancement=%s presentation=%s requested=%s execution=%s visible=%s hidden=%s",
            resource_plan.core_agents,
            resource_plan.enhancement_agents,
            resource_plan.presentation_agents,
            resource_plan.requested_agents,
            resource_plan.execution_agents,
            resource_plan.visible_agents,
            resource_plan.hidden_dependency_agents,
        )

        final: dict[str, dict] = {}
        context_bag: dict[str, dict] = {}
        completed_count = 0
        total_agents = len(resource_plan.ordered_agents)
        visible_set = set(resource_plan.visible_agents)
        hidden_set = set(resource_plan.hidden_dependency_agents)
        visible_completed_count = 0
        visible_total = len(resource_plan.visible_agents)

        for stage_key, stage_label, stage_agents in iter_plan_phases(resource_plan):
            if not stage_agents:
                logger.info("[Coordinator] 跳过空阶段: stage=%s", stage_key)
                continue

            # 每个阶段都只读取当前已完成的黑板结果，避免下游拿到半成品。
            logger.info(
                "[Coordinator] 进入阶段: stage=%s label=%s agents=%s shared_memory_keys=%s",
                stage_key,
                stage_label,
                stage_agents,
                list(context_bag.keys()),
            )
            await self.emitter.emit_workflow(
                stage_key,
                f"阶段 [{stage_label}] 已启动，正在分配 {len(stage_agents)} 个智能体...",
            )
            for agent_name in stage_agents:
                await self.emitter.emit_agent_status(
                    agent_name,
                    "queued",
                    f"等待进入 {stage_label}",
                    stage=stage_key,
                    visible=agent_name in visible_set,
                    dependency_only=agent_name in hidden_set,
                )

            futures = [
                asyncio.create_task(
                    self._run_agent_with_name(
                        agent_name=agent_name,
                        params=resource_plan.agent_parameters.get(agent_name, {}),
                        profile=snapshot.as_agent_profile(),
                        personalized_context=personalized_context,
                        shared_memory=context_bag,
                        visible_agents=visible_set,
                    )
                )
                for agent_name in stage_agents
            ]

            for future in asyncio.as_completed(futures):
                agent_name, result = await future
                final[agent_name] = result
                if result.get("success"):
                    # 只有成功产物才写回黑板，避免坏结果污染后续依赖链。
                    context_bag[agent_name] = result
                    logger.info("[Coordinator] 黑板已更新: agent=%s keys=%s", agent_name, list(context_bag.keys()))
                else:
                    logger.warning(
                        "[Coordinator] Agent 未产出可用结果: agent=%s error=%r",
                        agent_name,
                        result.get("error"),
                    )
                completed_count += 1
                if agent_name in visible_set:
                    visible_completed_count += 1
                await self.emitter.emit_bundle_update(
                    completed=completed_count,
                    total=total_agents,
                    core_ready=self._core_ready(resource_plan, final),
                    latest_agent=agent_name,
                    visible_completed=visible_completed_count,
                    visible_total=visible_total,
                )
            logger.info("[Coordinator] 阶段结束: stage=%s completed=%s/%s", stage_key, completed_count, total_agents)

        await self.emitter.emit_workflow("persisting", "正在保存本次资源包...")
        try:
            await self._save_resource(user_id, task, resource_plan, final)
            await self.emitter.emit_agent_log("coordinator", "资源包已入库")
        except Exception as exc:
            logger.error("[Coordinator] 保存资源记录失败: %s", exc, exc_info=exc)
            await self.emitter.emit_agent_log("coordinator", f"资源包保存失败，将仅保留本次流式结果：{exc}")

        logger.info("[Coordinator] 执行结束: user_id=%s completed_agents=%s visible_agents=%s", user_id, list(final.keys()), resource_plan.visible_agents)
        await self.emitter.emit_done("资源包构建完成")
        visible_final = {
            agent: final[agent]
            for agent in resource_plan.visible_agents
            if agent in final
        }
        return visible_final

    async def _safe_load_profile(self, user_id: int) -> LearnerProfileSnapshot:
        try:
            snapshot = await self.profile_loader.load(user_id)
            summary = snapshot.profile_summary or "暂无长期画像"
            logger.info(
                "[Coordinator] 画像快照加载成功: user_id=%s major=%r knowledge_score=%r",
                user_id,
                snapshot.major,
                snapshot.knowledge_level_score,
            )
            await self.emitter.emit_agent_log("coordinator", f"画像加载成功：{summary}")
            return snapshot
        except Exception as exc:
            logger.error("[Coordinator] 画像加载失败: %s", exc, exc_info=exc)
            await self.emitter.emit_agent_log("coordinator", f"画像加载失败，将使用默认画像上下文：{exc}")
            return LearnerProfileSnapshot(user_id=user_id)

    async def _safe_build_plan(
        self,
        task: dict,
        snapshot: LearnerProfileSnapshot,
        personalized_context: PersonalizedTaskContext,
        allowed_agents: list[str] | None,
    ) -> ResourcePlan:
        base_plan = build_default_resource_plan(task, allowed_agents)
        logger.info(
            "[Coordinator] 默认资源计划已构建: ordered_agents=%s requested=%s execution=%s visible=%s hidden=%s",
            base_plan.ordered_agents,
            base_plan.requested_agents,
            base_plan.execution_agents,
            base_plan.visible_agents,
            base_plan.hidden_dependency_agents,
        )
        for parameters in base_plan.agent_parameters.values():
            # 这里先补齐画像增强参数，Planner 失败时也能继续执行默认流程。
            parameters["major"] = snapshot.major or parameters.get("major", "")
            parameters["extra"] = self._merge_extra(
                parameters.get("extra", ""),
                personalized_context,
            )

        try:
            planned_tasks = await self._plan(
                task=task,
                snapshot=snapshot,
                personalized_context=personalized_context,
                allowed_agents=base_plan.execution_agents,
                requested_agents=base_plan.requested_agents,
                hidden_dependency_agents=base_plan.hidden_dependency_agents,
            )
            logger.info("[Coordinator] Planner 规划成功，开始合并参数")
            return merge_planned_tasks_into_plan(base_plan, planned_tasks)
        except PlanningError as exc:
            logger.error("[Coordinator] 规划失败: %s", exc)
            await self.emitter.emit_agent_log("coordinator", f"规划失败，使用默认资源计划：{exc}")
            return base_plan
        except Exception as exc:
            logger.error("[Coordinator] 规划异常: %s", exc, exc_info=exc)
            await self.emitter.emit_agent_log("coordinator", "规划异常，使用默认资源计划")
            return base_plan

    async def _plan(
        self,
        task: dict,
        snapshot: LearnerProfileSnapshot,
        personalized_context: PersonalizedTaskContext,
        allowed_agents: list[str] | None,
        requested_agents: list[str] | None = None,
        hidden_dependency_agents: list[str] | None = None,
    ) -> list[dict]:
        if not PLANNER_PROMPT_PATH.exists():
            raise PlanningError(f"Planner prompt 不存在: {PLANNER_PROMPT_PATH}")

        resource_scope = (
            "未指定，默认生成全部资源类型。"
            if allowed_agents is None
            else (
                f"执行范围(含依赖补全): {', '.join(allowed_agents)}；"
                f"用户请求返回: {', '.join(requested_agents or [])}；"
                f"依赖补全(默认不返回前端): {', '.join(hidden_dependency_agents or []) or '无'}"
            )
        )
        prompt_text = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        formatted = prompt_text.format(
            user_input=json.dumps(task, ensure_ascii=False),
            profile=json.dumps(snapshot.as_agent_profile(), ensure_ascii=False),
            personalized_context=json.dumps(personalized_context.as_prompt_context(), ensure_ascii=False),
            resource_scope=resource_scope,
        )
        messages = [
            SystemMessage(content=formatted),
            HumanMessage(content="请根据以上信息生成资源任务规划。"),
        ]
        logger.info(
            "[Coordinator] 正在调用 Planner: course=%r allowed_agents=%s prompt_path=%s",
            task.get("course", ""),
            allowed_agents or "ALL",
            PLANNER_PROMPT_PATH,
        )
        # Planner 输出要求是 JSON：优先启用 JSON Mode，减少 code fence/解释性文字导致的解析失败。
        # 若后端不支持 response_format，则回退到普通调用（仍要求 prompt 输出 JSON）。
        try:
            planner_llm = self.llm.bind(response_format={"type": "json_object"})
            response = await planner_llm.ainvoke(messages)
        except Exception as exc:
            logger.warning("[Coordinator] Planner JSON Mode 不支持，fallback=plain error=%s", exc, exc_info=exc)
            response = await self.llm.ainvoke(messages)
        content = response.content.strip()
        if content.lstrip().startswith("```"):
            lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
            content = "\n".join(lines).strip()
        try:
            plan_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlanningError(f"Planner 输出不是合法 JSON: {exc}") from exc

        tasks = plan_payload.get("tasks", [])
        if not isinstance(tasks, list):
            raise PlanningError("Planner 输出缺少 tasks 列表")

        logger.info("[Coordinator] Planner 返回 %s 个任务", len(tasks))
        return self._filter_tasks_by_selection(tasks, allowed_agents)

    async def _run_agent(
        self,
        agent_name: str,
        params: dict,
        profile: dict,
        personalized_context: PersonalizedTaskContext,
        shared_memory: dict,
        visible_agents: set[str] | None = None,
    ) -> dict:
        entry = get_agent_registry()[agent_name]
        is_visible = True if visible_agents is None else (agent_name in visible_agents)
        logger.info(
            "[Coordinator] Agent 启动: agent=%s stage=%s visible=%s params_keys=%s shared_memory_keys=%s",
            agent_name,
            entry.stage,
            is_visible,
            list(params.keys()),
            list(shared_memory.keys()),
        )
        await self.emitter.emit_agent_status(
            agent_name,
            "running",
            f"{entry.role} 正在执行 {entry.desc}",
            visible=is_visible,
            dependency_only=not is_visible,
        )

        profile_summary = profile.get("profile_summary") or "暂无稳定画像摘要"
        await self.emitter.emit_agent_log(agent_name, f"已注入学习画像：{profile_summary}")
        if shared_memory:
            await self.emitter.emit_agent_log(agent_name, f"已读取上游成果：{', '.join(shared_memory.keys())}")
        else:
            await self.emitter.emit_agent_log(agent_name, "当前作为首批智能体启动，无上游成果依赖")

        kwargs: dict[str, Any] = {
            "topic": params.get("topic", ""),
            "course": params.get("course", ""),
            "major": params.get("major", ""),
            "gap": params.get("gap", ""),
            "user_profile": profile,
            "shared_memory": shared_memory,
            **entry.extra_kwargs,
        }
        if agent_name == "mindmap":
            # 导图 Agent 需要额外的学习目标和补充说明来调整导图粒度。
            kwargs["need"] = params.get("need", "review")
            kwargs["extra"] = params.get("extra", "")

        try:
            logger.info("[Coordinator] 调用 Agent 方法: agent=%s method=%s", agent_name, entry.method)
            fn = getattr(entry.agent_loader(), entry.method)
            result = await fn(**kwargs)
        except Exception as exc:
            logger.error("[Coordinator] Agent %s 执行失败: %s", agent_name, exc, exc_info=exc)
            message = str(exc)
            await self.emitter.emit_agent_status(agent_name, "failed", message)
            return {
                "success": False,
                "type": entry.type,
                "title": entry.role,
                "content": "",
                "error": message,
            }

        success = bool(result.get("success"))
        if success:
            summary = entry.result_summary(result)
            logger.info("[Coordinator] Agent 执行成功: agent=%s summary=%s", agent_name, summary)
            await self.emitter.emit_agent_status(
                agent_name,
                "success",
                f"生成完成：{summary}",
                visible=is_visible,
                dependency_only=not is_visible,
            )
            if is_visible:
                await self.emitter.emit_artifact_ready(agent_name, result)
            else:
                await self.emitter.emit_agent_log(
                    agent_name,
                    "该资源属于依赖补全产物，已用于下游执行，默认不对前端返回。",
                    visible=False,
                    dependency_only=True,
                )
        else:
            logger.warning(
                "[Coordinator] Agent 执行完成但未成功: agent=%s error=%r",
                agent_name,
                result.get("error"),
            )
            await self.emitter.emit_agent_status(
                agent_name,
                "failed",
                result.get("error", "生成失败"),
                visible=is_visible,
                dependency_only=not is_visible,
            )
        return result

    async def _run_agent_with_name(
        self,
        agent_name: str,
        params: dict,
        profile: dict,
        personalized_context: PersonalizedTaskContext,
        shared_memory: dict,
        visible_agents: set[str] | None = None,
    ) -> tuple[str, dict]:
        result = await self._run_agent(
            agent_name=agent_name,
            params=params,
            profile=profile,
            personalized_context=personalized_context,
            shared_memory=shared_memory,
            visible_agents=visible_agents,
        )
        return agent_name, result

    @staticmethod
    def _merge_extra(existing_extra: str, personalized_context: PersonalizedTaskContext) -> str:
        additions = []
        if personalized_context.target_difficulty:
            additions.append(f"推荐难度：{personalized_context.target_difficulty}")
        if personalized_context.explanation_style:
            additions.append(f"讲解风格：{'；'.join(personalized_context.explanation_style)}")
        if personalized_context.emphasis:
            additions.append(f"强调事项：{'；'.join(personalized_context.emphasis)}")
        parts = [part for part in [existing_extra, " | ".join(additions)] if part]
        return "\n".join(parts)

    @staticmethod
    def _normalize_selected_resources(selected_resources: list[str] | None) -> list[str] | None:
        if not selected_resources:
            return None

        normalized: list[str] = []
        seen: set[str] = set()
        registry = get_agent_registry()
        default_order = list(registry.keys())
        order_index = {name: idx for idx, name in enumerate(default_order)}

        for raw_name in selected_resources:
            name = str(raw_name).strip().lower()
            if not name or name not in registry or name in seen:
                continue
            normalized.append(name)
            seen.add(name)

        if not normalized:
            return None

        normalized.sort(key=lambda name: order_index[name])
        return normalized

    @staticmethod
    def _filter_tasks_by_selection(
        tasks: list[dict],
        allowed_agents: list[str] | None,
    ) -> list[dict]:
        if allowed_agents is None:
            return tasks
        allowed_set = set(allowed_agents)
        return [task for task in tasks if task.get("agent") in allowed_set]

    @staticmethod
    def _core_ready(plan: ResourcePlan, results: dict[str, dict]) -> bool:
        for agent_name in plan.core_agents:
            if not results.get(agent_name, {}).get("success"):
                return False
        return True

    @staticmethod
    async def _save_resource(
        user_id: int,
        task: dict,
        resource_plan: ResourcePlan,
        results: dict,
    ) -> None:
        from sqlmodel.ext.asyncio.session import AsyncSession
        from app.infra.models import GeneratedResource

        def _serialize(data: dict | None) -> str | None:
            if not data:
                return None
            return json.dumps(data, ensure_ascii=False)

        logger.info(
            "[Coordinator] 开始持久化资源包: user_id=%s course=%r result_keys=%s",
            user_id,
            task.get("course", ""),
            list(results.keys()),
        )
        successful_agents = [name for name, value in results.items() if value.get("success")]
        failed_agents = [name for name, value in results.items() if not value.get("success")]
        if failed_agents and successful_agents:
            status = "partial_success"
        elif failed_agents:
            status = "failed"
        else:
            status = "completed"
        async with AsyncSession(engine) as session:
            resource = GeneratedResource(
                user_id=user_id,
                course=task.get("course", ""),
                gap=task.get("gap", ""),
                need=task.get("need", "review"),
                request_extra=task.get("extra", ""),
                status=status,
                plan_result=json.dumps(resource_plan.model_dump(), ensure_ascii=False),
                mindmap_result=_serialize(results.get("mindmap")),
                content_result=_serialize(results.get("content")),
                code_result=_serialize(results.get("code")),
                quiz_result=_serialize(results.get("quiz")),
                reading_result=_serialize(results.get("reading")),
                image_result=_serialize(results.get("image")),
                ppt_result=_serialize(results.get("ppt")),
                video_result=_serialize(results.get("video")),
            )
            session.add(resource)
            await session.commit()
            logger.info(
                "[Coordinator] 资源包持久化完成: user_id=%s status=%s successful=%s failed=%s",
                user_id,
                status,
                successful_agents,
                failed_agents,
            )
