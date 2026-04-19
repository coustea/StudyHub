from typing import Optional, Annotated
from pydantic import BaseModel, Field, ConfigDict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from app.memory.service import memory_service
from app.infra.logging import get_logger
from app.infra.llm import get_deepseek_llm

logger = get_logger(__name__)

Score = Annotated[int, Field(ge=0, le=100)]


class ProfileExtraction(BaseModel):
    """Structured profile fields returned by the profile LLM."""
    model_config = ConfigDict(extra="forbid")

    should_update: bool = Field(
        default=False,
        description="是否需要更新画像。仅当最近对话出现稳定可复用学习特征变化时为 true，否则为 false。",
    )
    knowledge_level: Optional[str] = Field(default=None, description="知识基础: 当前专业、学情边界")
    knowledge_level_score: Optional[Score] = Field(default=None, description="知识基础评分(0-100)")
    cognitive_style: Optional[str] = Field(default=None, description="认知风格: 偏好视觉/案例/推导等")
    cognitive_style_score: Optional[Score] = Field(default=None, description="认知风格评分(0-100)")
    error_pattern: Optional[str] = Field(default=None, description="易错点偏好: 逻辑盲区、常犯错误")
    error_pattern_score: Optional[Score] = Field(default=None, description="易错模式评分(0-100)")
    learning_goal: Optional[str] = Field(default=None, description="学习目标: 考试/兴趣/职业等")
    learning_goal_score: Optional[Score] = Field(default=None, description="学习目标评分(0-100)")
    learning_history: Optional[str] = Field(default=None, description="学习历史: 过去经验、相关背景")
    learning_history_score: Optional[Score] = Field(default=None, description="学习历史评分(0-100)")
    interest_preference: Optional[str] = Field(default=None, description="兴趣偏好: 个人喜好、关注点")
    interest_preference_score: Optional[Score] = Field(default=None, description="兴趣偏好评分(0-100)")
    learning_pace: Optional[str] = Field(default=None, description="学习节奏: 频率、时长、突击/平稳")
    learning_pace_score: Optional[Score] = Field(default=None, description="学习节奏评分(0-100)")
    cognitive_level: Optional[str] = Field(default=None, description="认知水平: 深度思考、逻辑推演能力")
    cognitive_level_score: Optional[Score] = Field(default=None, description="认知水平评分(0-100)")
    profile_summary: Optional[str] = Field(default=None, description="画像总结: 用一句话概括整体学习状态")

PROFILE_BUILDER_PROMPT = """
# 角色与目标
你是一个顶尖的 AI 教育心理学家和学习画像建模引擎。你的任务是根据学生【原有的学习画像】、【已有长期记忆】和【最新的一段导师对话记录】，提炼出稳定、可复用、足够抽象的学习特征，合并生成包含 **8 个核心维度** 的【最新全局学习画像】。

# 8 个核心维度矩阵：
1. 知识基础 (Knowledge Level)
2. 认知风格 (Cognitive Style)
3. 易错点偏好 (Error Pattern)
4. 学习目标 (Learning Goal)
5. 学习历史 (Learning History)
6. 兴趣偏好 (Interest Preference)
7. 学习节奏 (Learning Pace)
8. 认知水平 (Cognitive Level)

# 原有学习画像：
{current_profile}

# 已有长期记忆（帮助判断哪些信息应该进入画像，哪些更适合留在长期记忆）：
{memory_context}

# 最新对话记录：
{chat_history}

# 更新与合并规则 (最高优先级)
0. **先判定是否更新**：先判断最近对话是否出现“稳定可复用学习特征变化”。若没有变化，`should_update=false`，并尽量保持其余字段为 null（不要臆造新画像内容）。
1. **合并而非覆盖**：如果最新对话中出现了新的特征（比如新的易错点、新兴趣），请将其与"原有学习画像"中的对应字段进行**逻辑合并**。保留旧信息，补充新信息。
2. **保持原有**：如果最新对话中没有涉及到某个维度的信息，请直接**照搬**"原有学习画像"中该字段的内容，绝对不能将其清空。
3. **状态更替**：如果最新对话中显示学生已经克服了之前的错误，或者改变了目标，请根据最新情况**修改**原有描述。
4. **空值处理**：如果某维度原来是空(null)，且最新对话也没体现，继续输出 null。
5. **全局总结**：请基于你合并后的所有维度，重新撰写 `profile_summary`，用一句话凝练该学生当前的学习状态。
6. **稳定优先**：只有相对稳定、跨主题可复用的特征才写入画像。一次性的题目失误、某节课的临时卡点、短期任务细节不要直接上升为全局画像。
7. **职责边界**：具体事实（例如考试日期、课程名称、某次作业、临时偏好）优先留在长期记忆；画像应保留更抽象、更稳定的模式和倾向。
8. **弱点抽象化**：不要把单一知识点错误直接写成全局 `error_pattern`。只有当对话反复体现出稳定的思维盲区、理解方式偏差或学习障碍时，才更新该字段。

# 评分规则
9. **维度评分**：对每个非空的维度字段，请同时输出一个 0-100 的整数评分。评分标准：
   - 0-30: 初级（了解概念，但缺乏实践或经常出错）
   - 31-60: 中级（有一定基础，能应用但不够熟练或深度不足）
   - 61-80: 良好（掌握较好，能灵活运用，有自省能力）
   - 81-100: 优秀（深入掌握，能举一反三，有系统性思考）
10. **评分依据**：评分应基于对话中展现的实际水平，而非主观臆测。如果某维度信息不足，请输出 null 而非猜测分数。
11. **合并评分**：如果原有评分存在且对话中没有新的相关证据，保留原有评分。如有新证据，合理调整。

# 输出格式要求（必须严格遵守）：
{format_instructions}
"""


class ProfileBuilderAgent:
    def __init__(self, memory=memory_service):
        self.memory = memory
        self.module_name = "mentor"
        self.llm = get_deepseek_llm(temperature=0.1, streaming=False)
        self.output_parser = PydanticOutputParser(pydantic_object=ProfileExtraction)

        self.prompt_template = ChatPromptTemplate.from_messages([
            ("human", PROFILE_BUILDER_PROMPT)
        ])

    @staticmethod
    def _clean_message_content(content: str) -> str:
        text = (content or "").strip()
        return (
            text.replace("[Attached Files:", "\n[Attached Files:")
            .replace("[Attached Image:", "\n[Attached Image:")
            .strip()
        )

    async def _invoke_structured(self, prompt) -> ProfileExtraction:
        resp = await self.llm.ainvoke(prompt.to_messages())
        raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return self.output_parser.parse(raw_text)

    @staticmethod
    def _select_dialogue_messages(recent_msgs: list) -> list:
        """Only keep user/assistant turns for profile synthesis."""
        return [
            msg
            for msg in recent_msgs
            if getattr(msg, "role", "") in {"user", "assistant"} and getattr(msg, "content", "").strip()
        ]

    async def _build_memory_context(self, user_id: int) -> str:
        """Provide existing memory context so profile updates stay abstract and non-duplicative."""
        memories_by_type = await self.memory.get_user_context_memories(
            user_id=user_id,
            per_type_limits={"preference": 2, "goal": 2, "weakness": 2, "fact": 2, "background": 2},
        )
        lines: list[str] = []
        for memory_type, items in memories_by_type.items():
            if not items:
                continue
            joined = "；".join(item.content for item in items)
            lines.append(f"- {memory_type}: {joined}")
        return "\n".join(lines) if lines else "暂无已有长期记忆。"

    def _build_chat_history(self, recent_msgs: list) -> str:
        filtered = self._select_dialogue_messages(recent_msgs)
        return "\n".join(
            f"[{msg.created_at.strftime('%m-%d %H:%M')}] {msg.role}: {self._clean_message_content(msg.content)}"
            for msg in filtered
        )

    async def build_profile(self, user_id: int, session_id: str | None = None) -> tuple[bool, bool]:
        """Refresh the user's single global profile from recent mentor dialogue."""
        effective_session = session_id
        if effective_session is None:
            sessions = await self.memory.get_user_chat_sessions(
                user_id=user_id, module=self.module_name, limit=1
            )
            if sessions:
                effective_session = sessions[0].id
            else:
                effective_session = f"user-{user_id}-default-mentor"

        logger.info(f"[ProfileBuilder] 开始为用户 {user_id} 执行画像合并更新 (session={effective_session})...")

        recent_msgs = await self.memory.get_recent_messages(
            user_id=user_id,
            session_id=effective_session,
            module=self.module_name,
            limit=20,
        )
        if not recent_msgs:
            logger.info(f"[ProfileBuilder] 用户 {user_id} 暂无新对话，无需更新。")
            return True, False

        dialogue_msgs = self._select_dialogue_messages(recent_msgs)
        if not dialogue_msgs:
            logger.info(f"[ProfileBuilder] 用户 {user_id} 暂无有效对话，无需更新。")
            return True, False

        logger.info(f"[ProfileBuilder] 找到用户 {user_id} 的 {len(dialogue_msgs)} 条有效近期对话，准备提取特征。")
        chat_history_str = self._build_chat_history(dialogue_msgs)
        memory_context = await self._build_memory_context(user_id)

        current_profile = await self.memory.get_user_profile(user_id)
        current_profile_str = "暂无原有画像（新用户）"

        if current_profile:
            profile_dict = current_profile.model_dump(exclude_unset=True,
                                                      exclude={"user_id", "updated_at", "created_at", "id"})
            if profile_dict:
                current_profile_str = "\n".join([f"- {k}: {v}" for k, v in profile_dict.items() if v])
                logger.info(f"[ProfileBuilder] 已加载用户 {user_id} 的现有画像。")

        logger.info(f"[ProfileBuilder] 正在请求 LLM 进行画像合并提取 (user_id={user_id})...")
        try:
            prompt = self.prompt_template.invoke({
                "current_profile": current_profile_str,
                "memory_context": memory_context,
                "chat_history": chat_history_str,
                "format_instructions": self.output_parser.get_format_instructions(),
            })
            updated_data = await self._invoke_structured(prompt)
            logger.info(f"[ProfileBuilder] LLM 提取成功 (user_id={user_id})")
        except Exception as e:
            logger.error(f"[ProfileBuilder] 画像提取与合并失败: {str(e)}")
            return False, False

        if not updated_data.should_update:
            logger.info(f"[ProfileBuilder] 用户 {user_id} 判定无需更新画像。")
            return True, False

        final_features = updated_data.model_dump(exclude_none=True)
        final_features.pop("should_update", None)

        if not final_features:
            logger.info(f"[ProfileBuilder] 用户 {user_id} 画像无实质性更新。")
            return True, False

        try:
            await self.memory.update_user_profile(
                user_id=user_id,
                features=final_features,
                change_reason=f"基于最近{len(dialogue_msgs)}条有效对话的显著特征增量合并"
            )
            logger.info(f"[ProfileBuilder] 用户 {user_id} 画像合并更新完毕！更新字段: {list(final_features.keys())}")
            return True, True
        except Exception as e:
            logger.error(f"[ProfileBuilder] 保存更新后的画像失败 (user_id={user_id}): {str(e)}")
            return False, False
