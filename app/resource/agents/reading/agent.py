"""
拓展阅读推荐 Agent。
基于 BaseResourceAgent 实现，并使用黑板模式与用户画像。
"""

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


from app.infra.logging import get_logger
from app.resource.base_agent import BaseResourceAgent, BaseAgentState
from app.resource.validation import (
    extract_last_ai_content,
    validate_json_response,
    make_validation_result,
)

logger = get_logger(__name__)


class ReadingItem(BaseModel):
    title: str
    author_or_source: str
    abstract: str
    relevance: str
    type: str


class ReadingOutput(BaseModel):
    recommendations: list[ReadingItem]


class ReadingState(BaseAgentState):
    recommendations_json: str
    parsed_recommendations: list


class ReadingAgent(BaseResourceAgent):
    """拓展阅读推荐 Agent。"""

    # 推荐列表输出必须是 JSON，启用 JSON Mode 让模型直接输出结构化对象（不依赖正则提取）。
    force_json_mode = True

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "list_directory", "file_tree", "find_files", "get_file_info",
    ]
    skill_names = []


    def __init__(self) -> None:
        super().__init__(
            name="ReadingAgent",
            agent_dir=Path(__file__).parent,
            state_schema=ReadingState,
            temperature=0.3,
        )

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        ctx = ""
        # 拓展阅读会参考正文大纲，尽量让推荐内容和当前学习主题保持同一上下文。
        if "content" in shared_memory:
            outline = shared_memory["content"].get("outline", "")
            if outline:
                ctx += f"【内容大纲】\n{outline}\n"
        return ctx

    def _format_user_profile(self, profile: dict[str, Any]) -> str:
        # 兴趣偏好影响推荐方向，认知风格影响推荐材料的表达形式。
        if not profile: return ""
        parts = []
        if profile.get("interest_preference"):
            parts.append(f"- 兴趣偏好: {profile['interest_preference']}")
        if profile.get("cognitive_style"):
            parts.append(f"- 认知风格: {profile['cognitive_style']}")
        return "\n".join(parts)

    def _build_system_message(self, state: Any) -> str:
        user_profile = state.get("user_profile", {})
        system_prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", ""),
            topic=state.get("topic", ""),
            interest_preference=user_profile.get("interest_preference", ""),
            cognitive_style=user_profile.get("cognitive_style", ""),
        )
        return self._append_context_to_prompt(system_prompt, state)

    def _build_initial_human_message(self, state: Any) -> str:
        return f"请为主题 '{state.get('topic')}' 生成推荐阅读清单。"

    def _save_to_workplace(self, sub_dir: str, topic: str, content: str, ext: str = "md") -> str:
        from app.tools.file_operator import save_to_workplace
        # 阅读推荐同样落成 JSON，后续前端更容易做卡片列表和外链跳转。
        return save_to_workplace(
            sub_dir=sub_dir,
            topic=topic,
            content=content,
            ext=ext,
        )

    def _failure_result(
        self,
        state: Any,
        feedback: str,
        **fields: Any,
    ) -> dict[str, Any]:
        """构建可终止的失败返回，避免校验失败后继续空转。"""
        retry_count = state.get("retry_count", 0)
        result = make_validation_result(False, retry_count, feedback, **fields)
        if result["retry_count"] >= state.get("max_retries", 2):
            result["error"] = feedback
        return result

    async def _validate_node(self, state: Any) -> dict:
        messages = state.get("messages", [])
        retry_count = state.get("retry_count", 0)
        # 只验证最后产出的 JSON 主体，不把中间解释文字一起带进解析器。
        raw = extract_last_ai_content(messages)

        error = state.get("error")
        if error or not raw:
            return self._failure_result(
                state,
                error or "未生成推荐内容",
                recommendations_json=raw,
                parsed_recommendations=[],
            )

        logger.info("[ReadingAgent] _validate_node: 评审推荐质量")

        is_valid, feedback, validated, extra = validate_json_response(
            raw, ReadingOutput, retry_count, "推荐结构"
        )
        if not is_valid:
            failure = {**extra, "recommendations_json": raw, "parsed_recommendations": []}
            failure["error"] = failure.get("validation_feedback") or feedback
            return failure

        items = validated.recommendations
        # 至少保证有一个“小列表”，否则阅读推荐对用户帮助太弱。
        if len(items) < 3:
            return self._failure_result(
                state,
                f"推荐数量不足（{len(items)} 条），至少需要 5 条。",
                recommendations_json=raw,
                parsed_recommendations=[],
            )

        for i, item in enumerate(items):
            # 摘要过短通常意味着模型只是罗列标题，没有给出为什么值得读。
            if len(item.abstract) < 20:
                return self._failure_result(
                    state,
                    f"第 {i + 1} 条推荐摘要过短（'{item.title}'），请补充实质性内容。",
                    recommendations_json=raw,
                    parsed_recommendations=[],
                )

        types = {item.type for item in items}
        # 这里要求资源类型至少有两种，避免全是“书籍”或全是“论文”。
        if len(types) < 2:
            return self._failure_result(
                state,
                f"推荐类型单一（仅 {types}），请混合不同类型的资源。",
                recommendations_json=raw,
                parsed_recommendations=[],
            )

        logger.info(f"[ReadingAgent] 评审通过: {len(items)} 条推荐, 类型={types}")
        return {
            "recommendations_json": raw,
            "is_valid": True,
            "validation_feedback": "",
            "parsed_recommendations": [item.model_dump() for item in items],
            "error": None,
        }

    async def generate_reading(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[ReadingAgent] 收到生成请求: topic={topic}")
        await self._ensure_graph()

        # 运行时状态里保留 recommendations_json，便于失败时直接定位原始模型输出。
        initial_state: ReadingState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "recommendations_json": "",
            "is_valid": False,
            "validation_feedback": "",
            "parsed_recommendations": [],
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
        }

        try:
            logger.info("[ReadingAgent] 开始执行阅读推荐工作流")
            result = await self.graph.ainvoke(initial_state, {"recursion_limit": 15})
            logger.info(
                "[ReadingAgent] 工作流完成: is_valid=%s recommendation_count=%d",
                result.get("is_valid"),
                len(result.get("parsed_recommendations", []) or []),
            )
        except Exception as e:
            logger.error(f"[ReadingAgent] 工作流执行失败: {e}")
            return {"success": False, "recommendations": [], "raw_json": "", "error": str(e)}

        parsed = result.get("parsed_recommendations", [])
        raw_json = result.get("recommendations_json", "")
        file_path = None
        if parsed:
            file_path = self._save_to_workplace(
                "reading",
                topic,
                json.dumps(parsed, ensure_ascii=False, indent=2),
                "json",
            )
            logger.info("[ReadingAgent] 推荐清单已保存: file_path=%s item_count=%d", file_path, len(parsed))

        return {
            "success": bool(parsed),
            "recommendations": parsed,
            "file_path": file_path,
            "raw_json": raw_json,
            "error": result.get("error") if not parsed else None,
        }
