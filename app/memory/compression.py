"""
记忆压缩服务。

从 MemoryService 拆分：短期→长期记忆压缩（LLM 摘要）。
职责：当短期消息 token 总量达到阈值时，调用 LLM 对旧消息进行总结提炼，
将摘要写入长期记忆，并清理已总结的短期消息。
"""

from app.infra.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate

from app.infra.database import engine
from app.infra.logging import get_logger
from app.memory.short_term import short_term_service
from app.memory.long_term import long_term_service
from app.memory.memory_types import MEMORY_TYPE_SUMMARY

logger = get_logger(__name__)


class CompressionService:
    """短期→长期记忆压缩：当短期消息 token 总量达到阈值时，调用 LLM 总结并清理。"""

    def __init__(self) -> None:
        self.engine = engine  # 复用全局数据库引擎

    async def summarize_and_compress(
        self,
        user_id: int,
        session_id: str,
        module: str,
        threshold: int = 150,
        keep_recent: int = 10,
    ) -> None:
        """如果短期消息 token 总量达到阈值，调用 LLM 总结为长期记忆并清理旧消息。
        流程：
        1. 检查短期消息 token 总量是否达到 threshold，未达到则直接返回
        2. 获取所有短期消息，取前 len-keep_recent 条作为待总结内容
        3. 调用 LLM 将对话提炼为结构化的知识点
        4. 将 LLM 输出作为 summary 类型长期记忆保存
        5. 删除已总结的旧短期消息，仅保留最近 keep_recent 条
        """
        # 检查是否达到总结阈值
        if not await short_term_service.should_summarize(user_id, session_id, module, threshold):
            logger.debug("[Compression] 未达总结阈值: session_id=%s, threshold=%d", session_id, threshold)
            return

        # 获取全部短期消息（用于总结和后续清理）
        recent_msgs = await short_term_service.get_recent_messages(user_id, session_id, module)
        if not recent_msgs:
            logger.debug("[Compression] 无短期消息可总结: session_id=%s", session_id)
            return

        # 构造待总结的文本：排除最近 keep_recent 条（这些仍需保留在短期记忆中）
        chat_text = "\n".join(
            f"[{m.created_at.strftime('%m-%d %H:%M')}] {m.role}: {m.content}"
            for m in recent_msgs[:-keep_recent]
        )
        if not chat_text.strip():
            logger.debug("[Compression] 待总结内容为空: session_id=%s, total_msgs=%d, keep_recent=%d",
                         session_id, len(recent_msgs), keep_recent)
            return

        # 构建 LLM 总结 prompt：要求将对话提炼为分类知识点
        summarize_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "你是一个记忆压缩引擎。请将以下对话记录提炼为若干条关键知识点和结论。\n"
                "每条用一行表示，格式：`类别|内容`，类别包括 knowledge/error/behavior/interest/question/answer。\n"
                "只输出有价值的条目，忽略闲聊。"
            )),
            ("human", "{chat_text}"),
        ])

        try:
            # 创建 LLM 实例（低温度以获得稳定的总结结果，复用缓存）
            llm = get_llm(temperature=0.1)
            logger.info("[Compression] 开始 LLM 总结: session_id=%s, user_id=%d, "
                        "msg_count=%d, to_summarize=%d, keep_recent=%d",
                        session_id, user_id, len(recent_msgs),
                        len(recent_msgs) - keep_recent, keep_recent)

            prompt = summarize_prompt.invoke({"chat_text": chat_text})
            result = await llm.ainvoke(prompt)
            logger.debug("[Compression] LLM 总结完成: session_id=%s, result_len=%d",
                         session_id, len(result.content))

            # 将总结结果作为长期记忆保存（类型为 summary，来源为 module）
            summarized_ids = [m.id for m in recent_msgs[:-keep_recent]]
            await long_term_service.save_long_term_memory(
                user_id=user_id,
                session_id=session_id,
                content=result.content,
                memory_type=MEMORY_TYPE_SUMMARY,  # 标记为摘要类型
                source=module,
                source_message_count=len(summarized_ids),  # 记录被总结的消息条数
            )

            # 删除已总结的旧短期消息
            deleted = await short_term_service.delete_old_messages(user_id, session_id, module, keep_recent)
            logger.info("[Compression] 压缩完成: user=%d, session_id=%s, "
                        "summarized=%d, deleted=%d, kept=%d",
                        user_id, session_id, len(summarized_ids), deleted, keep_recent)
        except Exception as e:
            logger.error("[Compression] 短期→长期压缩失败: session_id=%s, user_id=%d, error=%s",
                         session_id, user_id, e, exc_info=True)


compression_service = CompressionService()  # 模块级单例
