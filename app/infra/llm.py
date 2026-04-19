"""LLM client factory — 懒初始化，按需创建 LLM 客户端实例。

提供两个工厂函数：
  - get_llm(): 主力 LLM，@lru_cache 缓存，用于对话生成、记忆压缩等核心任务
  - get_fast_llm(): 轻量快速 LLM，不缓存，用于意图分类、路由判断等低延迟任务
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import (
    DEEPSEEK_API_BASE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_CHAT_MODEL,
    DEEPSEEK_MODEL,
    DEEPSEEK_REASONER_MODEL,
    FAST_LLM_API_BASE,
    FAST_LLM_API_KEY,
    FAST_LLM_MODEL,
    GLM_API_KEY,
    GLM_MODEL,
    GLM_VISION_MODEL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    SPARK_X_API_BASE,
    SPARK_X_API_KEY,
    SPARK_X_MODEL,
)
from app.infra.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=4)  # 最多缓存 4 组不同参数组合的实例
def get_llm(
    model: str | None = None,
    temperature: float = 0.3,
    streaming: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """创建或返回缓存的 LLM 客户端实例。
    缓存 key = (model, temperature, streaming, max_tokens)，相同参数复用同一实例。
    默认使用 OPENAI_MODEL 环境变量指定的模型。"""
    resolved_model = model or OPENAI_MODEL
    logger.debug("[LLM] 创建主力 LLM 实例: model=%s, temp=%.2f, streaming=%s, max_tokens=%s",
                 resolved_model, temperature, streaming, max_tokens)
    return ChatOpenAI(
        model=resolved_model,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE,  # OpenAI 兼容 API 端点
        temperature=temperature,
        streaming=streaming,
        max_tokens=max_tokens,
    )


@lru_cache(maxsize=2)
def get_deepseek_llm(
    model: str | None = None,
    temperature: float = 0.3,
    streaming: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """创建或返回缓存的 DeepSeek 文本 LLM 实例。"""
    resolved_model = model or DEEPSEEK_MODEL
    logger.debug(
        "[LLM] 创建 DeepSeek LLM 实例: model=%s, temp=%.2f, streaming=%s, max_tokens=%s",
        resolved_model, temperature, streaming, max_tokens,
    )
    return ChatOpenAI(
        model=resolved_model,
        api_key=DEEPSEEK_API_KEY or OPENAI_API_KEY,
        base_url=DEEPSEEK_API_BASE,
        temperature=temperature,
        streaming=streaming,
        max_tokens=max_tokens,
    )


@lru_cache(maxsize=2)
def get_deepseek_chat_llm(
    temperature: float = 0.3,
    streaming: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """获取 DeepSeek Chat 模型实例。"""
    return get_deepseek_llm(
        model=DEEPSEEK_CHAT_MODEL,
        temperature=temperature,
        streaming=streaming,
        max_tokens=max_tokens,
    )


@lru_cache(maxsize=2)
def get_deepseek_reasoner_llm(
    streaming: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """获取 DeepSeek Reasoner (R1) 模型实例。
    注意：推理模型通常建议使用默认 temperature (1.0) 或固定值，此处不开放 temp 调整。"""
    return get_deepseek_llm(
        model=DEEPSEEK_REASONER_MODEL,
        temperature=1.0,
        streaming=streaming,
        max_tokens=max_tokens,
    )

@lru_cache(maxsize=2)
def get_spark_x_llm(
    model: str | None = None,
    temperature: float = 0.3,
    streaming: bool = False,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """创建或返回缓存的 SparkMAX(Spark X) 文本 LLM 实例。"""
    resolved_model = model or SPARK_X_MODEL
    logger.debug(
        "[LLM] 创建 SparkX LLM 实例: model=%s, temp=%.2f, streaming=%s, max_tokens=%s",
        resolved_model, temperature, streaming, max_tokens,
    )
    return ChatOpenAI(
        model=resolved_model,
        api_key=SPARK_X_API_KEY or OPENAI_API_KEY,
        base_url=SPARK_X_API_BASE or OPENAI_API_BASE,
        temperature=temperature,
        streaming=streaming,
        max_tokens=max_tokens,
    )


@lru_cache(maxsize=2)
def get_glm_vision_llm(
    model: str | None = None,
    temperature: float = 0.7,
) -> ChatOpenAI:
    """创建或返回缓存的 GLM 视觉理解 LLM 实例。
    使用智谱 BigModel API，用于图片理解等多模态任务。"""
    resolved_model = model or GLM_VISION_MODEL
    logger.debug("[LLM] 创建 GLM 视觉 LLM 实例: model=%s, temp=%.2f",
                 resolved_model, temperature)
    return ChatOpenAI(
        model=resolved_model,
        api_key=GLM_API_KEY,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        temperature=temperature,
    )


def get_fast_llm(temperature: float = 0.0, max_tokens: int = 100) -> ChatOpenAI:
    """获取快速/分类 LLM 实例（不缓存，每次创建新实例）。
    使用 FAST_LLM_MODEL 环境变量指定的模型，默认 temperature=0 确保分类结果稳定。
    典型用途：消息路由分类、意图识别、模式判断等低延迟任务。"""
    model = FAST_LLM_MODEL
    logger.debug("[LLM] 创建快速 LLM 实例: model=%s, temp=%.2f, max_tokens=%d",
                 model, temperature, max_tokens)
    return ChatOpenAI(
        model=model,
        api_key=FAST_LLM_API_KEY or OPENAI_API_KEY,  # 回退到主 API key
        base_url=FAST_LLM_API_BASE or OPENAI_API_BASE,
        temperature=temperature,
        max_tokens=max_tokens,
    )
