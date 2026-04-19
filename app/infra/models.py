"""
统一 SQLModel 表定义。

所有数据库表集中在此文件中定义，按功能域分组：
  - User       用户基础信息
  - Auth       JWT Token 白名单
  - Chat       会话与消息（短期记忆）
  - Memory     长期记忆
  - Profile    用户画像及历史快照
  - Resource   生成资源记录

新表应添加到 REGISTERED_MODELS 元组中，以便 init_db() 自动创建。
"""

import uuid
from datetime import datetime

from sqlalchemy import Text, Column
from sqlmodel import SQLModel, Field

from app.infra.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# User — 用户基础信息
# ---------------------------------------------------------------------------

class User(SQLModel, table=True):
    """用户基础信息表"""
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)  # 自增主键
    username: str = Field(max_length=50, index=True, unique=True)  # 用户名，唯一索引
    password: str = Field(max_length=255, exclude=True)  # bcrypt 哈希密码，exclude=True 防止序列化泄露
    email: str | None = Field(default=None, max_length=100)
    avatar: str | None = Field(default=None, max_length=500)  # 头像 URL
    major: str | None = Field(default=None, max_length=100)  # 专业
    grade: str | None = Field(default=None, max_length=20)  # 年级
    school: str | None = Field(default=None, max_length=100)  # 学校
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Auth — JWT Token 白名单（登出时从白名单移除）
# ---------------------------------------------------------------------------

class ActiveToken(SQLModel, table=True):
    """活跃 Token 白名单表 — 用于支持登出失效和强制下线"""
    __tablename__ = "active_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)  # 关联用户，支持按用户批量清理 token
    token: str = Field(unique=True, index=True)  # JWT 字符串，唯一索引用于快速查找
    expires_at: datetime  # token 过期时间，用于清理过期记录
    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Chat — 会话与消息（短期记忆载体）
# ---------------------------------------------------------------------------

class ChatSession(SQLModel, table=True):
    """会话表 — 管理多会话隔离，每个用户可以有多个独立会话"""
    __tablename__ = "chat_sessions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)  # UUID 字符串主键
    user_id: int = Field(index=True)
    module: str = Field(index=True)  # 所属功能模块（如 "profile_builder"）
    title: str = Field(default="新对话", max_length=100)  # 会话标题（取首条消息前 20 字符）
    is_archived: bool = Field(default=False)  # 软删除标记

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)  # 每次写入消息时更新
    memory_token_count: int = Field(default=0)  # 记忆提取 token 累计（达到阈值触发 FactAgent）
    profile_token_count: int = Field(default=0)  # 画像更新 token 累计（达到阈值触发 ProfileAgent）


class ChatMessage(SQLModel, table=True):
    """短期记忆表 — 存储用户的原始聊天记录，按会话隔离"""
    __tablename__ = "chat_messages"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    session_id: str = Field(index=True)  # 关联 ChatSession
    module: str = Field(default="profile_builder", index=True)
    role: str  # 消息角色："user" | "assistant" | "system" | "tool"
    content: str = Field(sa_column=Column(Text))  # 消息正文，使用 Text 类型支持长文本
    attachments: str | None = Field(default=None, sa_column=Column(Text))  # 附件信息（JSON 字符串）
    tool_calls: str | None = Field(default=None, sa_column=Column(Text))  # 工具调用记录（JSON 字符串）
    created_at: datetime = Field(default_factory=datetime.now, index=True)  # 创建时间索引，用于过期清理


# ---------------------------------------------------------------------------
# Memory — 长期记忆
# ---------------------------------------------------------------------------

class UserMemory(SQLModel, table=True):
    """统一长期记忆表 — 存储经过提炼的用户知识/偏好/目标等持久化记忆"""
    __tablename__ = "user_memory"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    session_id: str = Field(default="", index=True)  # 来源会话
    content: str = Field(sa_column=Column(Text))  # 记忆正文
    memory_type: str = Field(index=True)  # 类型：preference | goal | weakness | fact | background | summary
    dimension: str | None = None  # 可选维度标签（画像维度关联）
    importance: float = Field(default=0.5)  # 重要性评分 0.0~1.0
    source: str = Field(default="conversation", index=True)  # 来源："fact_agent" | "conversation" | module名
    source_message_count: int = Field(default=0)  # 来源消息条数（用于压缩溯源）
    expires_at: datetime | None = Field(default=None)  # 过期时间（null 表示永不过期）
    evidence_count: int = Field(default=1)  # 该记忆被观察到的次数（去重累加）
    last_seen_at: datetime = Field(default_factory=datetime.now)  # 最后一次出现时间
    attachments: str | None = Field(default=None, sa_column=Column(Text))  # 附件信息
    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Profile — 用户画像及历史快照
# ---------------------------------------------------------------------------

class UserProfile(SQLModel, table=True):
    """用户画像表 — 存储用户当前的学习画像状态（8 维度 + 摘要）
    主键为 user_id（非自增），与 User 表一对一关系。"""
    __tablename__ = "user_profiles"

    user_id: int = Field(primary_key=True)  # 与 User.id 一对一

    # 8 个画像维度，每个维度包含描述文本 + 评分（0~100）
    knowledge_level: str | None = Field(default=None, sa_column=Column(Text))  # 知识水平描述
    knowledge_level_score: int | None = Field(default=None)  # 知识水平评分
    learning_goal: str | None = Field(default=None, sa_column=Column(Text))  # 学习目标
    learning_goal_score: int | None = Field(default=None)
    learning_history: str | None = Field(default=None, sa_column=Column(Text))  # 学习经历
    learning_history_score: int | None = Field(default=None)
    cognitive_style: str | None = Field(default=None, sa_column=Column(Text))  # 认知风格
    cognitive_style_score: int | None = Field(default=None)
    error_pattern: str | None = Field(default=None, sa_column=Column(Text))  # 错误模式
    error_pattern_score: int | None = Field(default=None)
    learning_pace: str | None = Field(default=None, sa_column=Column(Text))  # 学习节奏
    learning_pace_score: int | None = Field(default=None)
    interest_preference: str | None = Field(default=None, sa_column=Column(Text))  # 兴趣偏好
    interest_preference_score: int | None = Field(default=None)
    cognitive_level: str | None = Field(default=None, sa_column=Column(Text))  # 认知水平
    cognitive_level_score: int | None = Field(default=None)

    profile_summary: str | None = Field(default=None, sa_column=Column(Text))  # 画像总摘要

    updated_at: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)


class UserProfileHistory(SQLModel, table=True):
    """用户画像历史表 — 记录每次画像变更的快照，用于追踪画像演化过程"""
    __tablename__ = "user_profile_history"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    version: int = Field(index=True)  # 版本号，每次更新递增

    # 与 UserProfile 相同的 8 维度字段（快照）
    knowledge_level: str | None = Field(default=None, sa_column=Column(Text))
    knowledge_level_score: int | None = Field(default=None)
    learning_goal: str | None = Field(default=None, sa_column=Column(Text))
    learning_goal_score: int | None = Field(default=None)
    learning_history: str | None = Field(default=None, sa_column=Column(Text))
    learning_history_score: int | None = Field(default=None)
    cognitive_style: str | None = Field(default=None, sa_column=Column(Text))
    cognitive_style_score: int | None = Field(default=None)
    error_pattern: str | None = Field(default=None, sa_column=Column(Text))
    error_pattern_score: int | None = Field(default=None)
    learning_pace: str | None = Field(default=None, sa_column=Column(Text))
    learning_pace_score: int | None = Field(default=None)
    interest_preference: str | None = Field(default=None, sa_column=Column(Text))
    interest_preference_score: int | None = Field(default=None)
    cognitive_level: str | None = Field(default=None, sa_column=Column(Text))
    cognitive_level_score: int | None = Field(default=None)

    profile_summary: str | None = Field(default=None, sa_column=Column(Text))

    change_reason: str | None = Field(default=None, sa_column=Column(Text))  # 变更原因（如"系统自动更新"）
    source_memory_ids: str | None = Field(default=None, sa_column=Column(Text))  # 触发变更的记忆 ID 列表（JSON）

    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Resource — 生成资源记录
# ---------------------------------------------------------------------------

class GeneratedResource(SQLModel, table=True):
    """生成资源记录表 — 记录每次多智能体资源生成的输入参数和各阶段产出"""
    __tablename__ = "generated_resources"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    course: str = Field(max_length=200)  # 课程/主题名称
    gap: str = Field(sa_column=Column(Text))  # 知识缺口描述
    need: str = Field(default="review", max_length=50)  # 需求类型（如 "review"、"learn"）
    request_extra: str | None = Field(default=None, sa_column=Column(Text))  # 用户附加要求
    status: str = Field(default="completed", max_length=50)  # 生成状态
    plan_result: str | None = Field(default=None, sa_column=Column(Text))  # DAG 规划结果（JSON）

    # 各资源 Agent 的产出结果（JSON 字符串）
    mindmap_result: str | None = Field(default=None, sa_column=Column(Text))  # 思维导图
    content_result: str | None = Field(default=None, sa_column=Column(Text))  # 内容讲解
    code_result: str | None = Field(default=None, sa_column=Column(Text))  # 代码示例
    quiz_result: str | None = Field(default=None, sa_column=Column(Text))  # 练习题
    reading_result: str | None = Field(default=None, sa_column=Column(Text))  # 延伸阅读
    image_result: str | None = Field(default=None, sa_column=Column(Text))  # 配图
    ppt_result: str | None = Field(default=None, sa_column=Column(Text))  # PPT 大纲
    video_result: str | None = Field(default=None, sa_column=Column(Text))  # 视频

    created_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Model registration — init_db() 通过此元组获取所有需要建表的模型类
# ---------------------------------------------------------------------------

REGISTERED_MODELS = (
    ActiveToken,
    ChatSession,
    ChatMessage,
    UserMemory,
    UserProfile,
    UserProfileHistory,
    GeneratedResource,
    User,
)


def import_all_models() -> tuple[type, ...]:
    """返回已注册的模型类元组，同时确保所有模型类被导入以触发 SQLModel 元数据注册。
    init_db() 调用此函数后再执行 create_all，才能正确建表。"""
    logger.debug("[Models] 已注册 %d 个模型: %s",
                 len(REGISTERED_MODELS),
                 [m.__name__ for m in REGISTERED_MODELS])
    return REGISTERED_MODELS