import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import AliasChoices, BaseModel, Field, field_validator

CONFIG_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CONFIG_DIR.parents[1]
CONFIG_YAML_PATH = CONFIG_DIR / "config.yaml"
ENV_FILE_PATH = BACKEND_DIR / ".env"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")
_UNSET = object()


class AppConfig(BaseModel):
    """应用基础配置。"""

    name: str = "FrameForge"
    env: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class JwtConfig(BaseModel):
    """JWT 认证配置。"""

    secret_key: str = Field(
        default="dev-only-secret-change-in-production-at-least-32-bytes",
        min_length=32,
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)


class LlmConfig(BaseModel):
    """对应 langchain_openai.ChatOpenAI 的模型参数配置。"""

    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, ge=1)
    timeout: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


class AgentConfig(BaseModel):
    """Agent 运行配置。"""

    workspace_dir: Path = Field(
        default=BACKEND_DIR / "workspaces",
        validation_alias=AliasChoices("workspace_dir", "workspaces", "workspace"),
    )
    skills_dir: Path = Field(
        default=BACKEND_DIR / "app/agent/skills",
        validation_alias=AliasChoices("skills_dir", "skills"),
    )
    llm: LlmConfig = Field(default_factory=LlmConfig)

    tavily: str = ""

    @field_validator("workspace_dir", "skills_dir", mode="before")
    @classmethod
    def _resolve_backend_path(cls, value: Any) -> Path:
        """自动将相对路径解析为相对于后端项目根目录（BACKEND_DIR）的绝对路径。"""
        if isinstance(value, Path):
            path = value
        elif isinstance(value, str):
            path = Path(value.strip())
        else:
            path = Path(str(value))
        if not path.is_absolute():
            return (BACKEND_DIR / path).resolve()
        return path.resolve()

    @property
    def workspaces(self) -> Path:
        """工作区目录路径别名。"""
        return self.workspace_dir

    @property
    def skills(self) -> Path:
        """Skills 目录路径别名。"""
        return self.skills_dir


class MysqlConfig(BaseModel):
    """MySQL 连接与连接池配置。"""

    host: str = "127.0.0.1"
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(default="frameforge", pattern=r"^[a-zA-Z0-9_]+$")
    username: str = "root"
    password: str = ""
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=20, ge=0)


class RedisConfig(BaseModel):
    """Redis 基础连接配置。"""

    addr: str = "127.0.0.1"
    port: int = Field(default=6379, ge=1, le=65535)
    password: str | None = None
    db: int = Field(default=0, ge=0)


class DatabaseConfig(BaseModel):
    """数据库分组配置（MySQL + Redis）。"""

    mysql: MysqlConfig = Field(default_factory=MysqlConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)


class Settings(BaseModel):
    """系统根配置模型，仅负责结构化承载 config.yaml 与 .env 读取结果。"""

    app: AppConfig = Field(default_factory=AppConfig)
    jwt: JwtConfig = Field(default_factory=JwtConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def _resolve_placeholders(value: Any, env_map: dict[str, str]) -> Any:
    """递归解析 YAML 值中的 ${VAR} / ${VAR:-default} 环境变量占位符。"""
    if isinstance(value, dict):
        resolved: dict[str, Any] = {}
        for key, item in value.items():
            parsed = _resolve_placeholders(item, env_map)
            if parsed is not _UNSET:
                resolved[key] = parsed
        return resolved

    if isinstance(value, list):
        return [
            item
            for item in (_resolve_placeholders(v, env_map) for v in value)
            if item is not _UNSET
        ]

    if not isinstance(value, str):
        return value

    # 整值仅为单个无默认值的 ${VAR} 且未设置环境变量时，保留模型默认值
    full_match = _ENV_PATTERN.fullmatch(value.strip())
    if full_match and full_match.group(2) is None and full_match.group(1) not in env_map:
        return _UNSET

    return _ENV_PATTERN.sub(
        lambda m: env_map.get(m.group(1), m.group(2) or ""),
        value,
    )


_current_settings: Settings | None = None


def load_settings(
    yaml_path: Path = CONFIG_YAML_PATH,
    env_path: Path = ENV_FILE_PATH,
) -> Settings:
    """读取 config.yaml 并结合 .env 与系统环境变量生成 Settings 实例。"""
    env_map: dict[str, str] = {}
    if env_path.is_file():
        for key, val in dotenv_values(env_path).items():
            if val is not None:
                env_map[key] = val
    env_map.update(os.environ)

    raw_data: dict[str, Any] = {}
    if yaml_path.is_file():
        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw_data = loaded

    resolved = _resolve_placeholders(raw_data, env_map)
    return Settings.model_validate(resolved)


def set_settings(settings: Settings) -> None:
    """缓存当前运行时使用的全局配置实例。"""
    global _current_settings
    _current_settings = settings


def get_settings() -> Settings:
    """获取当前全局配置实例，尚未初始化时按默认路径加载。"""
    global _current_settings
    if _current_settings is None:
        _current_settings = load_settings()
    return _current_settings
