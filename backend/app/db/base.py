from sqlmodel import SQLModel

from app.models.message import Message
from app.models.project import Project
from app.models.task import Task
from app.models.user import User

# 汇总 SQLModel 元数据，便于外部迁移工具或测试环境统一引用已注册表模型
target_metadata = SQLModel.metadata

__all__ = ["Message", "Project", "SQLModel", "Task", "User", "target_metadata"]
