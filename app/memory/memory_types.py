"""长期记忆类型常量与类型定义（单一真源）。"""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

# 数据库 user_memory.memory_type 允许值
MEMORY_TYPE_PREFERENCE: Final[str] = "preference"
MEMORY_TYPE_GOAL: Final[str] = "goal"
MEMORY_TYPE_WEAKNESS: Final[str] = "weakness"
MEMORY_TYPE_FACT: Final[str] = "fact"
MEMORY_TYPE_BACKGROUND: Final[str] = "background"
MEMORY_TYPE_SUMMARY: Final[str] = "summary"

ALL_MEMORY_TYPES: Final[tuple[str, ...]] = (
    MEMORY_TYPE_PREFERENCE,
    MEMORY_TYPE_GOAL,
    MEMORY_TYPE_WEAKNESS,
    MEMORY_TYPE_FACT,
    MEMORY_TYPE_BACKGROUND,
    MEMORY_TYPE_SUMMARY,
)

# FactAgent 只产出这 5 类，不含 summary
FACT_AGENT_MEMORY_TYPES: Final[tuple[str, ...]] = (
    MEMORY_TYPE_PREFERENCE,
    MEMORY_TYPE_GOAL,
    MEMORY_TYPE_WEAKNESS,
    MEMORY_TYPE_FACT,
    MEMORY_TYPE_BACKGROUND,
)

MemoryType: TypeAlias = Literal[
    "preference",
    "goal",
    "weakness",
    "fact",
    "background",
    "summary",
]

FactAgentMemoryType: TypeAlias = Literal[
    "preference",
    "goal",
    "weakness",
    "fact",
    "background",
]

