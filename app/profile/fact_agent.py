from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from app.memory.service import memory_service
from app.memory.memory_types import FactAgentMemoryType
from app.infra.logging import get_logger
from app.memory.helpers import normalize_text
from app.infra.llm import get_deepseek_llm

logger = get_logger(__name__)

MEMORY_NON_SIGNIFICANT_TEXTS = {"谢谢", "好的", "收到", "明白了", "继续", "再来一道题", "ok", "OK"}
MEMORY_SIGNIFICANT_KEYWORDS = (
    "我是", "我在", "我用", "我现在", "我准备", "我想", "我不喜欢", "我更喜欢",
    "下周", "期末", "考试", "证书", "专业", "基础", "习惯", "薄弱", "总是", "经常"
)

class ExtractedFactItem(BaseModel):
    """One candidate memory item extracted from recent dialogue."""
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, description="提取出的事实内容，尽量简练具体。比如：'目前正在使用 Python 3.13'")
    memory_type: FactAgentMemoryType = Field(description="事实分类：preference / fact / goal / weakness / background")
    is_time_sensitive: bool = Field(default=False, description="该事实是否具有时效性（如'下周三要考试'、'本学期在学数据结构'）")
    expires_in_days: Optional[int] = Field(default=None, gt=0, description="如果有时效性，预计多少天后过期。如考试倒计时7天则填7。无时效性填 null")

    @field_validator("content")
    @classmethod
    def _clean_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("content 不能为空")
        return cleaned

class FactExtraction(BaseModel):
    """Structured batch of fact-memory candidates."""
    model_config = ConfigDict(extra="forbid")

    has_fact: bool = Field(description="对话中是否包含值得长期记忆的用户特定事实、偏好、目标等")
    facts: list[ExtractedFactItem] = Field(default_factory=list, description="提取出的长期记忆候选列表，最多 3 条")

FACT_BUILDER_PROMPT = """
# 角色与目标
你是一个专业的长期记忆抽取引擎。你的任务是从用户的【最新导师对话记录】中，提取值得写入【长期记忆池】的用户事实、偏好、目标、背景或稳定弱点。

# 提取准则
1. **只关注核心事实**：比如用户的年级、使用的具体技术栈版本（如 Python 3.13）、个人的明确喜好（"不要给我看英文文档"）、近期明确目标（"下周三要考数据结构"）。
2. **忽略闲聊与通用问题**：不要把用户问的具体知识点（如"什么是二叉树"）当做长期事实。只有当问题反映出他的某种长期状态时才提取。
3. **时效性判断**：如果事实与某个时间节点相关（如考试、学期、截止日期），请标记 is_time_sensitive=true 并估算 expires_in_days。永久性事实（如"专业是计算机"）标记为 false。
4. **宁缺毋滥**：如果不确定是否有值得记忆的事实，请将 has_fact 设为 false。
5. **不要重复已有记忆**：如果信息和已有长期记忆本质相同，不要重复输出；只有更具体、更近期或更有价值时才输出。
6. **与画像分工**：抽取具体事实、具体目标、具体偏好、背景信息和可复用的稳定弱点；不要输出画像式总结。
7. **数量限制**：最多输出 3 条，优先最有价值、最能帮助后续辅导的内容。

# 当前用户画像（帮助判断什么属于长期事实，什么只是表达风格）：
{profile_context}

# 已有长期记忆：
{memory_context}

# 最新对话记录：
{chat_history}

# 输出格式要求（必须严格遵守）：
{format_instructions}
"""


class MemoryExtractionAgent:
    def __init__(self, memory=memory_service):
        self.memory = memory
        self.module_name = "mentor"
        self.llm = get_deepseek_llm(temperature=0.1, streaming=False)
        self.output_parser = PydanticOutputParser(pydantic_object=FactExtraction)
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("human", FACT_BUILDER_PROMPT)
        ])

    @staticmethod
    def _normalize_text(text: str) -> str:
        return normalize_text(text)

    async def _invoke_structured(self, prompt) -> FactExtraction:
        resp = await self.llm.ainvoke(prompt.to_messages())
        raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return self.output_parser.parse(raw_text)

    @staticmethod
    def _select_dialogue_messages(recent_msgs: list) -> list:
        """Only keep user/assistant turns for memory extraction prompts."""
        return [
            msg
            for msg in recent_msgs
            if getattr(msg, "role", "") in {"user", "assistant"} and getattr(msg, "content", "").strip()
        ]

    def _build_chat_history(self, recent_msgs: list) -> str:
        filtered = self._select_dialogue_messages(recent_msgs)
        return "\n".join(
            f"[{msg.created_at.strftime('%m-%d %H:%M')}] {msg.role}: {msg.content}"
            for msg in filtered
        )

    def _has_extractable_signal(self, recent_msgs: list) -> bool:
        """Skip LLM extraction when recent user turns contain no stable-memory signal."""
        user_texts: list[str] = []
        ignore = {self._normalize_text(t) for t in MEMORY_NON_SIGNIFICANT_TEXTS}
        for msg in recent_msgs[-6:]:
            if msg.role != "user":
                continue
            cleaned = self._normalize_text(msg.content)
            if not cleaned or cleaned in ignore:
                continue
            user_texts.append(cleaned)

        if not user_texts:
            return False

        joined = "\n".join(user_texts)
        if any(keyword.lower() in joined for keyword in MEMORY_SIGNIFICANT_KEYWORDS):
            return True
        return any("我" in text and len(text) >= 18 for text in user_texts)

    async def _build_memory_context(self, user_id: int) -> str:
        """Summarize existing memories so the extractor can avoid redundant output."""
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

    async def _build_profile_context(self, user_id: int) -> str:
        """Expose the current profile so fact extraction stays scoped to concrete memories."""
        profile = await self.memory.get_user_profile(user_id)
        if not profile:
            return "暂无用户画像。"
        profile_dict = profile.model_dump(exclude_unset=True, exclude={"user_id", "updated_at", "created_at"})
        profile_lines = [f"- {key}: {value}" for key, value in profile_dict.items() if value]
        return "\n".join(profile_lines) if profile_lines else "暂无用户画像。"

    async def extract_and_save_fact(self, user_id: int, session_id: str) -> bool:
        """Extract and persist user-level long-term memories from recent mentor chat."""
        logger.info(f"[FactAgent] 开始为用户 {user_id} 提炼长期事实记忆...")
        recent_msgs = await self.memory.get_recent_messages(
            user_id=user_id,
            session_id=session_id,
            module=self.module_name,
            limit=8
        )

        if not recent_msgs or len(recent_msgs) < 1:
            return True

        dialogue_msgs = self._select_dialogue_messages(recent_msgs)
        if not dialogue_msgs:
            return True

        if not self._has_extractable_signal(dialogue_msgs):
            logger.info(f"[FactAgent] 最近对话缺少长期记忆信号，跳过提取。")
            return True

        chat_history_str = self._build_chat_history(dialogue_msgs)
        profile_context = await self._build_profile_context(user_id)
        memory_context = await self._build_memory_context(user_id)

        try:
            prompt = self.prompt_template.invoke({
                "profile_context": profile_context,
                "memory_context": memory_context,
                "chat_history": chat_history_str,
                "format_instructions": self.output_parser.get_format_instructions(),
            })
            extracted = await self._invoke_structured(prompt)

            if extracted.has_fact and extracted.facts:
                saved_count = 0
                for item in extracted.facts[:3]:
                    expires_at = None
                    if item.is_time_sensitive and item.expires_in_days and item.expires_in_days > 0:
                        from datetime import timedelta
                        expires_at = datetime.now() + timedelta(days=item.expires_in_days)

                    # MemoryService owns deduplication, merge, and timestamp refresh.
                    logger.info(f"[FactAgent] 提取到新事实: {item.content} (type={item.memory_type})")
                    try:
                        await self.memory.save_user_fact(
                            user_id=user_id,
                            content=item.content,
                            memory_type=item.memory_type,
                            session_id=session_id,
                            expires_at=expires_at,
                        )
                    except ValueError as exc:
                        logger.info(
                            "[FactAgent] 跳过无效事实: content=%r type=%s reason=%s",
                            item.content,
                            item.memory_type,
                            exc,
                        )
                        continue
                    saved_count += 1
                logger.info(f"[FactAgent] 本轮共处理 {saved_count} 条长期记忆候选。")
            else:
                logger.info(f"[FactAgent] 本次对话无新增事实。")
            return True
        except Exception as e:
            logger.error(f"[FactAgent] 事实提炼失败: {str(e)}")
            return False
