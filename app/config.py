"""
统一配置模块。

从环境变量读取所有配置，提供 typed settings。
此模块是唯一的 `.env` 读取入口。
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    return float(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default).lower()) in ("true", "1", "yes")


# Server
SERVER_HOST: str = _env("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = _env_int("SERVER_PORT", 9999)

# Database
DB_HOST: str = _env("DB_HOST", "localhost")
DB_PORT: int = _env_int("DB_PORT", 3306)
DB_USER: str = _env("DB_USER", "root")
DB_PASSWORD: str = _env("DB_PASSWORD")
DB_NAME: str = _env("DB_NAME", "agent")
DB_ECHO: bool = _env_bool("DB_ECHO", False)
DB_POOL_SIZE: int = _env_int("DB_POOL_SIZE", 10)
DB_MAX_OVERFLOW: int = _env_int("DB_MAX_OVERFLOW", 20)
DB_POOL_RECYCLE: int = _env_int("DB_POOL_RECYCLE", 1800)
DB_POOL_TIMEOUT: int = _env_int("DB_POOL_TIMEOUT", 30)
DB_INIT_MAX_RETRIES: int = _env_int("DB_INIT_MAX_RETRIES", 5)
DB_INIT_RETRY_DELAY_SEC: float = _env_float("DB_INIT_RETRY_DELAY_SEC", 1.5)

# JWT
JWT_SECRET_KEY: str = _env("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS: int = _env_int("JWT_EXPIRE_DAYS", 7)

# LLM
OPENAI_API_KEY: str = _env("OPENAI_API_KEY", "")
OPENAI_MODEL: str = _env("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_BASE: str = _env("OPENAI_API_BASE", "")

# SparkLite
FAST_LLM_MODEL: str = _env("FAST_LLM_MODEL", "general")
FAST_LLM_API_BASE: str = _env("FAST_LLM_API_BASE", OPENAI_API_BASE)
FAST_LLM_API_KEY: str = _env("FAST_LLM_API_KEY", OPENAI_API_KEY)

# GLM
GLM_MODEL: str = _env("GLM_MODEL", "glm-4.7")

# Deepseek
DEEPSEEK_API_KEY: str = _env("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE: str = _env("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
DEEPSEEK_CHAT_MODEL: str = _env("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL: str = _env("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")
DEEPSEEK_MODEL: str = _env("DEEPSEEK_MODEL", DEEPSEEK_CHAT_MODEL)

# Spark X
SPARK_X_API_KEY: str = _env("SPARK_X_API_KEY", OPENAI_API_KEY)
SPARK_X_MODEL: str = _env("SPARK_X_MODEL", OPENAI_MODEL)
SPARK_X_API_BASE: str = _env("SPARK_X_API_BASE", OPENAI_API_BASE)

# Vision
GLM_VISION_MODEL: str = _env("GLM_VISION_MODEL", "glm-4v-flash")
GLM_API_KEY: str = _env("GLM_API_KEY", "")

# Agent
LLM_TIMEOUT: int = _env_int("LLM_TIMEOUT", 300)
MAX_MESSAGE_HISTORY: int = _env_int("MAX_MESSAGE_HISTORY", 20)
PROFILE_GATE_EVERY_N_ASSISTANT_TURNS: int = _env_int("PROFILE_GATE_EVERY_N_ASSISTANT_TURNS", 2)
CONTENT_AGENT_TIMEOUT_SECONDS: int = _env_int("CONTENT_AGENT_TIMEOUT_SECONDS", 360)
CONTENT_LLM_TIMEOUT: int = _env_int("CONTENT_LLM_TIMEOUT", 180)
MULTIMODAL_DOC_ENABLED: bool = _env_bool("MULTIMODAL_DOC_ENABLED", True)

# Debug
APP_DEBUG: bool = _env_bool("APP_DEBUG", False)
LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")

# Image Generation (星火图片生成)
SPARK_IMAGE_GENERATION_APPID: str = _env("SPARK_IMAGE_GENERATION_APPID", "")
SPARK_IMAGE_GENERATION_API_KEY: str = _env("SPARK_IMAGE_GENERATION_API_KEY", "")
SPARK_IMAGE_GENERATION_APP_SECRET: str = _env("SPARK_IMAGE_GENERATION_APP_SECRET", "")
SPARK_IMAGE_GENERATION_ENABLED: bool = _env_bool("SPARK_IMAGE_GENERATION_ENABLED", False)

# Spark Vision (星火图片理解)
SPARK_VISION_APPID: str = _env("SPARK_IMAGE_APPID", "")
SPARK_VISION_API_KEY: str = _env("SPARK_IMAGE_API_KEY", "")
SPARK_VISION_API_SECRET: str = _env("SPARK_IMAGE_API_SECRET", "")

# Avatar (数字人)
AVATAR_ASR_APP_ID: str = _env("AVATAR_ASR_APP_ID", "")
AVATAR_ASR_API_KEY: str = _env("AVATAR_ASR_API_KEY", "")
AVATAR_ASR_API_SECRET: str = _env("AVATAR_ASR_API_SECRET", "")
AVATAR_APP_ID: str = _env("AVATAR_APP_ID", "")
AVATAR_API_KEY: str = _env("AVATAR_API_KEY", "")
AVATAR_API_SECRET: str = _env("AVATAR_API_SECRET", "")
AVATAR_URL: str = _env("AVATAR_URL", "wss://avatar.cn-huadong-1.xf-yun.com/v1/interact")
ANCHOR_ID: str = _env("ANCHOR_ID", "110017006")
VCN: str = _env("VCN", "x4_yezi")
IAT_URL: str = _env("IAT_URL", "wss://iat-api.xfyun.cn/v2/iat")
AVATAR_BRIDGE_PORT: int = _env_int("AVATAR_BRIDGE_PORT", 8765)

# Aliases for ASR (shared app_id/key/secret for ASR and Spark LLM)
ASR_SPARK_APP_ID: str = AVATAR_ASR_APP_ID or _env("ASR_SPARK_APP_ID", "")
ASR_SPARK_API_KEY: str = AVATAR_ASR_API_KEY or _env("ASR_SPARK_API_KEY", "")
ASR_SPARK_API_SECRET: str = AVATAR_ASR_API_SECRET or _env("ASR_SPARK_API_SECRET", "")

# Paths
WORKPLACE_DIR: str = _env("WORKPLACE_DIR", "workplace")
LOGS_DIR: str = _env("LOGS_DIR", "logs")
KNOWLEDGE_BASE_DIR: str = _env("KNOWLEDGE_BASE_DIR", "data")
