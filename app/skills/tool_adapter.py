"""Adapter that exposes skills as normalized LLM-callable tools."""

from __future__ import annotations

from collections.abc import Mapping

from langchain.tools import tool
from langchain_core.tools import BaseTool

from app.skills.runtime import SkillRuntime
from app.skills.models import SkillSpec


class SkillToolAdapter:
    """Convert discovered skills into Claude-Code-style unified tools."""

    def __init__(self, runtime: SkillRuntime, *, max_hint_items: int = 20) -> None:
        self.runtime = runtime
        self.max_hint_items = max_hint_items

    def _build_runtime_hint(self, spec: SkillSpec) -> str:
        scripts = self.runtime.list_resources(spec, "scripts")
        examples = self.runtime.list_resources(spec, "examples")
        references = self.runtime.list_resources(spec, "references")
        assets = self.runtime.list_resources(spec, "assets")

        lines = [
            "",
            "## Runtime Capabilities",
            "- 指令加载: `skill(name=...)`",
            "- 资源读取: `skill_read(name=..., kind=..., relative_path=...)`",
            "- 脚本执行: `skill_run(name=..., script_path=..., script_args=...)`",
        ]
        if examples:
            lines.append("### 示例资源（节选）")
            lines.extend(f"- `{item}`" for item in examples[: self.max_hint_items])
        if references:
            lines.append("### 参考资源（节选）")
            lines.extend(f"- `{item}`" for item in references[: self.max_hint_items])
        if assets:
            lines.append("### 资产资源（节选）")
            lines.extend(f"- `{item}`" for item in assets[: self.max_hint_items])
        if scripts:
            lines.append("### 可执行脚本（节选）")
            lines.extend(f"- `{item}`" for item in scripts[: self.max_hint_items])
        return "\n".join(lines)

    def build_unified_tools(self, specs: Mapping[str, SkillSpec]) -> list[BaseTool]:
        """Return Claude-Code style unified tools for a scope of skills."""
        spec_map = dict(specs)
        sorted_names = sorted(spec_map)

        def _resolve(name: str) -> SkillSpec | None:
            return spec_map.get((name or "").strip())

        @tool(description="列出当前作用域内可用的技能名称。")
        async def _skill_list() -> str:
            if not sorted_names:
                return "当前没有可用技能。"
            return "可用技能:\n" + "\n".join(f"- {name}" for name in sorted_names)

        _skill_list.name = "skill_list"

        @tool(description="Claude Code 风格技能调用：按 name 加载技能指令。")
        async def _skill(name: str, include_resources: bool = True) -> str:
            spec = _resolve(name)
            if spec is None:
                return f"技能不存在: {name}。请先调用 skill_list 查看可用技能。"
            instructions = self.runtime.read_instructions(spec)
            if not include_resources:
                return instructions
            return instructions + self._build_runtime_hint(spec)

        _skill.name = "skill"

        @tool(description="读取技能资源。kind: scripts|examples|references|assets。")
        async def _skill_read(
            name: str,
            kind: str,
            relative_path: str = "",
            max_chars: int = 12000,
            binary: bool = False,
        ) -> str:
            spec = _resolve(name)
            if spec is None:
                return f"技能不存在: {name}。"
            if kind not in {"scripts", "examples", "references", "assets"}:
                return f"不支持的 kind: {kind}（可选: scripts/examples/references/assets）"
            _, message = self.runtime.read_resource(
                spec,
                kind,  # type: ignore[arg-type]
                relative_path,
                max_chars=max_chars,
                binary=binary,
            )
            return message

        _skill_read.name = "skill_read"

        @tool(description="执行技能脚本。script_path 为空时返回 scripts 列表。")
        async def _skill_run(
            name: str,
            script_path: str = "",
            script_args: str = "",
            timeout_sec: int = 120,
        ) -> str:
            spec = _resolve(name)
            if spec is None:
                return f"技能不存在: {name}。"
            return await self.runtime.run_script(
                spec,
                script_path,
                script_args=script_args,
                timeout_sec=timeout_sec,
            )

        _skill_run.name = "skill_run"

        return [_skill_list, _skill, _skill_read, _skill_run]
