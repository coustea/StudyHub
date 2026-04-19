from __future__ import annotations

from typing import Any

from app.infra.logging import get_logger
from app.resource.schemas import ResourcePlan

logger = get_logger(__name__)

CORE_AGENTS = ["content", "mindmap", "quiz"]
ENHANCEMENT_AGENTS = ["reading", "code", "image"]
PRESENTATION_AGENTS = ["ppt", "video"]
ALL_AGENTS = CORE_AGENTS + ENHANCEMENT_AGENTS + PRESENTATION_AGENTS

DEFAULT_DEPENDENCIES: dict[str, list[str]] = {
    "content": [],
    "mindmap": [],
    "quiz": ["content"],
    "reading": ["content"],
    "code": ["mindmap", "content"],
    "image": ["content", "mindmap"],
    "ppt": ["content", "mindmap", "image"],
    "video": ["content", "image", "ppt"],
}


def expand_dependencies(selected: list[str], dependency_map: dict[str, list[str]]) -> list[str]:
    """展开资源依赖闭包，并按系统固定顺序输出。

    说明：
    - 输入是用户显式选择的资源（可能是部分资源）
    - 输出是“执行集合”：包含 selected 本身 + 所有递归依赖
    - 顺序按半动态编排既有顺序（core -> enhancement -> presentation），避免引入全动态 DAG
    """
    if not selected:
        return []

    closure: set[str] = set()
    stack = list(selected)
    while stack:
        current = stack.pop()
        if current in closure:
            continue
        closure.add(current)
        stack.extend(dependency_map.get(current, []))

    ordered = [agent for agent in ALL_AGENTS if agent in closure]
    # 兼容未来扩展：如果出现未登记到 ALL_AGENTS 的 agent，保持原输入次序追加到末尾。
    for agent in selected:
        if agent in closure and agent not in ordered:
            ordered.append(agent)
    return ordered


def build_default_resource_plan(
    task: dict[str, Any],
    allowed_agents: list[str] | None,
) -> ResourcePlan:
    if allowed_agents:
        requested_agents = [agent for agent in ALL_AGENTS if agent in set(allowed_agents)]
        execution_agents = expand_dependencies(requested_agents, DEFAULT_DEPENDENCIES)
        visible_agents = list(requested_agents)
        hidden_dependency_agents = [agent for agent in execution_agents if agent not in set(visible_agents)]
    else:
        requested_agents = list(ALL_AGENTS)
        execution_agents = list(ALL_AGENTS)
        visible_agents = list(ALL_AGENTS)
        hidden_dependency_agents = []

    execution_set = set(execution_agents)
    logger.info(
        "[Planning] 构建默认资源计划: course=%r requested=%s execution=%s visible=%s hidden=%s",
        task.get("course", ""),
        requested_agents,
        execution_agents,
        visible_agents,
        hidden_dependency_agents,
    )

    def _params() -> dict[str, Any]:
        return {
            "topic": task.get("course", ""),
            "major": task.get("major", ""),
            "course": task.get("course", ""),
            "gap": task.get("gap", ""),
            "need": task.get("need", "review"),
            "extra": task.get("extra", ""),
        }

    return ResourcePlan(
        core_agents=[agent for agent in CORE_AGENTS if agent in execution_set],
        enhancement_agents=[agent for agent in ENHANCEMENT_AGENTS if agent in execution_set],
        presentation_agents=[agent for agent in PRESENTATION_AGENTS if agent in execution_set],
        requested_agents=requested_agents,
        execution_agents=execution_agents,
        visible_agents=visible_agents,
        hidden_dependency_agents=hidden_dependency_agents,
        dependencies={
            agent: [dep for dep in DEFAULT_DEPENDENCIES.get(agent, []) if dep in execution_set]
            for agent in execution_agents
        },
        agent_parameters={agent: _params() for agent in execution_agents},
    )


def merge_planned_tasks_into_plan(
    plan: ResourcePlan,
    tasks: list[dict[str, Any]],
) -> ResourcePlan:
    for task in tasks:
        agent = task.get("agent")
        if agent not in plan.agent_parameters:
            logger.warning("[Planning] 跳过未注册的 Planner 任务: agent=%r", agent)
            continue
        parameters = task.get("parameters") or {}
        # 这里先保留默认参数，再用 planner 输出覆盖，避免 planner 漏字段时把执行链打断。
        merged = {**plan.agent_parameters[agent], **parameters}
        plan.agent_parameters[agent] = merged
        logger.info("[Planning] 已合并 Planner 参数: agent=%s keys=%s", agent, list(parameters.keys()))
    return plan


def iter_plan_phases(plan: ResourcePlan) -> list[tuple[str, str, list[str]]]:
    # video 单独拆到最后一段，确保它依赖的 PPT 和图解已经稳定产出。
    presentation_agents = [agent for agent in plan.presentation_agents if agent != "video"]
    video_agents = [agent for agent in plan.presentation_agents if agent == "video"]
    phases = [
        ("core_generating", "核心资源生成", plan.core_agents),
        ("enhancement_generating", "增强资源补充", plan.enhancement_agents),
        ("presentation_generating", "演示资源生成", presentation_agents),
        ("video_generating", "视频资源生成", video_agents),
    ]
    logger.info("[Planning] 阶段划分完成: %s", phases)
    return phases
