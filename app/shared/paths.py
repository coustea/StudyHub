"""全局路径常量。"""
from pathlib import Path

from app.config import KNOWLEDGE_BASE_DIR as KNOWLEDGE_BASE_DIR_NAME
from app.config import LOGS_DIR as LOGS_DIR_NAME
from app.config import WORKPLACE_DIR as WORKPLACE_DIR_NAME

SERVER_DIR = Path(__file__).resolve().parents[2]
WORKPLACE_DIR = SERVER_DIR / WORKPLACE_DIR_NAME
LOGS_DIR = SERVER_DIR / LOGS_DIR_NAME
KNOWLEDGE_BASE_DIR = SERVER_DIR / KNOWLEDGE_BASE_DIR_NAME
