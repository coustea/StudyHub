"""Shared models for skills discovery and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SkillSpec:
    """Normalized metadata for one discovered skill package."""

    name: str
    description: str
    root_dir: Path
    skill_file: Path
    keywords: list[str] = field(default_factory=list)
