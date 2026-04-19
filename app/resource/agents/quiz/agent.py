"""
分层练习题生成 Agent。
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


class QuizQuestion(BaseModel):
    difficulty: str = Field(description="basic | intermediate | challenge")
    question_type: str = Field(description="choice | short_answer | true_false")
    stem: str = Field(description="题干")
    options: list[str] | None = Field(default=None, description="选择题选项")
    answer: str = Field(description="正确答案")
    explanation: str = Field(description="解析")


class QuizOutput(BaseModel):
    questions: list[QuizQuestion]


class QuizState(BaseAgentState):
    questions_json: str
    parsed_questions: list


class QuizAgent(BaseResourceAgent):
    """分层练习题生成 Agent。"""

    # 题目输出必须是 JSON，启用 JSON Mode 让模型直接输出结构化对象（不依赖正则提取）。
    force_json_mode = True

    tool_names = [
        "save_to_workplace", "read_file_safe",
        "write_file", "edit_file", "append_file", "read_file_lines",
        "list_directory", "file_tree", "find_files", "get_file_info",
    ]
    skill_names = []


    def __init__(self) -> None:
        super().__init__(
            name="QuizAgent",
            agent_dir=Path(__file__).parent,
            state_schema=QuizState,
            temperature=0.3,
        )

    def _extract_memory(self, shared_memory: dict[str, Any]) -> str:
        ctx = ""
        # 题目生成依赖正文大纲，能帮助模型围绕已讲过的结构出题。
        if "content" in shared_memory:
            outline = shared_memory["content"].get("outline", "")
            if outline:
                ctx += f"【内容大纲】\n{outline}\n"
        return ctx

    def _format_user_profile(self, profile: dict[str, Any]) -> str:
        # 这里只选择“知识水平”和“易错模式”两个最直接影响题目设计的字段。
        if not profile: return ""
        parts = []
        if profile.get("error_pattern"):
            parts.append(f"- 易错模式: {profile['error_pattern']}")
        if profile.get("knowledge_level"):
            parts.append(f"- 知识水平: {profile['knowledge_level']}")
        return "\n".join(parts)

    def _build_system_message(self, state: Any) -> str:
        user_profile = state.get("user_profile", {})
        system_prompt = self.prompt_template.format(
            major=state.get("major", "通用"),
            course=state.get("course", ""),
            topic=state.get("topic", ""),
            gap=state.get("gap", ""),
            knowledge_level=user_profile.get("knowledge_level", "中等"),
            error_pattern=user_profile.get("error_pattern", ""),
        )
        return self._append_context_to_prompt(system_prompt, state)

    def _build_initial_human_message(self, state: Any) -> str:
        return f"请为主题 '{state.get('topic')}' 生成一套分层练习题。"

    def _save_to_workplace(self, sub_dir: str, topic: str, content: str, ext: str = "md") -> str:
        from app.tools.file_operator import save_to_workplace
        # 题目最终以 json 保存，方便前端直接渲染成练习卡片或测验页面。
        return save_to_workplace(
            sub_dir=sub_dir,
            topic=topic,
            content=content,
            ext=ext,
        )

    async def _validate_node(self, state: Any) -> dict:
        messages = state.get("messages", [])
        retry_count = state.get("retry_count", 0)
        # 校验时只取最后一条 AI 文本，避免系统提示或工具输出干扰 JSON 解析。
        raw = extract_last_ai_content(messages)

        error = state.get("error")
        if error or not raw:
            return make_validation_result(
                False, retry_count, error or "未生成题目内容",
                questions_json=raw, parsed_questions=[],
            )

        logger.info("[QuizAgent] _validate_node: 校验题目结构")

        is_valid, feedback, validated, extra = validate_json_response(
            raw, QuizOutput, retry_count, "题目结构"
        )
        if not is_valid:
            return {**extra, "questions_json": raw, "parsed_questions": []}

        questions = validated.questions
        # 先校验最小题量，避免生成出来只有一两道题就直接当成功。
        if len(questions) < 3:
            return make_validation_result(
                False, retry_count,
                f"题目数量不足（{len(questions)} 道），至少需要 6 道题。",
                questions_json=raw, parsed_questions=[],
            )

        difficulties = {q.difficulty for q in questions}
        # 再校验难度分层是否真的生效，确保“分层练习题”不是名义上的。
        if len(difficulties) < 2:
            return make_validation_result(
                False, retry_count,
                f"难度分布单一（仅 {difficulties}），需要至少覆盖 2 个难度层级。",
                questions_json=raw, parsed_questions=[],
            )

        logger.info(f"[QuizAgent] 校验通过: {len(questions)} 道题, 难度分布={difficulties}")
        return {
            "questions_json": raw,
            "is_valid": True,
            "validation_feedback": "",
            "parsed_questions": [q.model_dump() for q in questions],
        }

    async def generate_quiz(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict = None,
        shared_memory: dict = None,
    ) -> dict[str, Any]:
        logger.info(f"[QuizAgent] 收到生成请求: topic={topic}")
        await self._ensure_graph()

        # 这里初始化 parsed_questions，后面校验成功后会直接覆盖成结构化列表。
        initial_state: QuizState = {
            "major": major,
            "course": course,
            "topic": topic,
            "gap": gap,
            "user_profile": user_profile or {},
            "shared_memory": shared_memory or {},
            "messages": [],
            "questions_json": "",
            "is_valid": False,
            "validation_feedback": "",
            "parsed_questions": [],
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
        }

        try:
            logger.info("[QuizAgent] 开始执行题目生成工作流")
            result = await self.graph.ainvoke(initial_state, {"recursion_limit": 15})
            logger.info(
                "[QuizAgent] 工作流完成: is_valid=%s parsed_count=%d",
                result.get("is_valid"),
                len(result.get("parsed_questions", []) or []),
            )
        except Exception as e:
            logger.error(f"[QuizAgent] 工作流执行失败: {e}")
            return {"success": False, "questions": [], "raw_json": "", "error": str(e)}

        parsed = result.get("parsed_questions", [])
        raw_json = result.get("questions_json", "")
        file_path = None
        if parsed:
            file_path = self._save_to_workplace("quiz", topic, json.dumps(parsed, ensure_ascii=False, indent=2), "json")
            logger.info("[QuizAgent] 题库已保存: file_path=%s question_count=%d", file_path, len(parsed))

        return {
            "success": bool(parsed),
            "questions": parsed,
            "file_path": file_path,
            "raw_json": raw_json,
            "error": result.get("error") if not parsed else None,
        }
