"""Skills Manager: discover, parse, and register skill packages."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool

from app.infra.logging import get_logger
from app.skills.models import SkillSpec
from app.skills.runtime import SkillRuntime
from app.skills.tool_adapter import SkillToolAdapter

logger = get_logger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent


class SkillManager:
    """Discover skills and expose normalized tools for agents."""

    def __init__(
        self,
        skills_path: Path | list[Path] | tuple[Path, ...] | None = None,
        *,
        runtime: SkillRuntime | None = None,
        tool_adapter: SkillToolAdapter | None = None,
        **_: Any,
    ) -> None:
        if skills_path is None:
            skills_path = DEFAULT_SKILLS_DIR
        self._skills_paths = self._normalize_skills_paths(skills_path)
        self._skill_specs: dict[str, SkillSpec] = {}
        self._scoped_tools: dict[tuple[str, ...], list[BaseTool]] = {}
        self._load_lock = asyncio.Lock()
        self.runtime = runtime or SkillRuntime()
        self.tool_adapter = tool_adapter or SkillToolAdapter(self.runtime)

    @staticmethod
    def _normalize_skills_paths(
        skills_path: Path | list[Path] | tuple[Path, ...] | None,
    ) -> list[Path]:
        if skills_path is None:
            return []
        if isinstance(skills_path, Path):
            return [skills_path]
        return [p for p in skills_path if p is not None]

    async def load_all(self) -> None:
        """Thread-safe entrypoint for discovery + registration."""
        async with self._load_lock:
            self._load_skills()

    def _load_skills(self) -> None:
        """Discover skill specs only (tool registration is scope-based at get_tools())."""
        for skills_path in self._skills_paths:
            if not skills_path.exists():
                continue
            for skill_md in skills_path.rglob("SKILL.md"):
                self._parse_skill(skill_md)

    def _parse_skill(self, filepath: Path) -> None:
        try:
            content = filepath.read_text(encoding="utf-8")
            match = FRONTMATTER_RE.match(content)
            if not match:
                return
            frontmatter = yaml.safe_load(match.group(1))
            if not isinstance(frontmatter, dict):
                return

            name = str(frontmatter.get("name", filepath.parent.name))
            if name in self._skill_specs:
                return

            spec = SkillSpec(
                name=name,
                description=str(frontmatter.get("description", "No description")),
                root_dir=filepath.parent,
                skill_file=filepath,
                keywords=list(frontmatter.get("keywords", [])),
            )
            self._skill_specs[name] = spec
        except Exception as exc:
            logger.error("[SkillManager] parse failed %s: %s", filepath, exc)

    def read_skill_instructions(self, name: str) -> str | None:
        """Read SKILL.md instructions for one discovered skill."""
        spec = self._skill_specs.get(name)
        if not spec:
            return None
        return self.runtime.read_instructions(spec)

    async def get_tools(self, skill_names: list[str] | None = None) -> list[BaseTool]:
        """Return normalized tools for all or selected skills."""
        selected_names = sorted(self._skill_specs.keys()) if skill_names is None else sorted(
            name for name in skill_names if name in self._skill_specs
        )
        scope_key = tuple(selected_names)
        if scope_key not in self._scoped_tools:
            scoped_specs = {name: self._skill_specs[name] for name in selected_names}
            self._scoped_tools[scope_key] = self.tool_adapter.build_unified_tools(scoped_specs)
        return self._scoped_tools[scope_key]

    def list_skills(self) -> list[dict[str, Any]]:
        """List discovered skills and registered tool names."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "keywords": spec.keywords,
                "tool_name": "skill",
                "tool_names": ["skill_list", "skill", "skill_read", "skill_run"],
            }
            for spec in sorted(self._skill_specs.values(), key=lambda item: item.name)
        ]

    async def aclose(self) -> None:
        self._skill_specs.clear()
        self._scoped_tools.clear()
