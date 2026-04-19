"""Skill runtime that executes discovered skill packages."""

from __future__ import annotations

import asyncio
import base64
import re
import shlex
import sys
from pathlib import Path
from typing import Literal

from app.skills.models import SkillSpec

ResourceKind = Literal["scripts", "examples", "references", "assets"]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SCRIPT_EXTENSIONS = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs"}
TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".xml",
    ".toml",
    ".ini",
    ".rst",
}


class SkillRuntime:
    """Execute a skill package with guarded file access and script execution."""

    def __init__(self, *, max_list_items: int = 80, max_output_chars: int = 12000) -> None:
        self.max_list_items = max_list_items
        self.max_output_chars = max_output_chars

    @staticmethod
    def _ensure_within_root(root_dir: Path, candidate: Path) -> bool:
        root = root_dir.resolve()
        target = candidate.resolve()
        return target == root or root in target.parents

    @staticmethod
    def _trim_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n\n... (输出已截断，总长度 {len(text)} 字符)"

    @staticmethod
    def _kind_roots(spec: SkillSpec, kind: ResourceKind) -> list[Path]:
        root = spec.root_dir
        if kind == "scripts":
            return [root / "scripts"]
        if kind == "examples":
            return [root / "examples", root / "references" / "examples", root / "reference" / "examples"]
        if kind == "references":
            return [root / "references", root / "reference"]
        if kind == "assets":
            return [root / "assets"]
        return []

    def read_instructions(self, spec: SkillSpec) -> str:
        content = spec.skill_file.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(content)
        return content[match.end():].strip() if match else content.strip()

    def list_resources(self, spec: SkillSpec, kind: ResourceKind) -> list[str]:
        paths: set[str] = set()
        roots = self._kind_roots(spec, kind)
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(spec.root_dir).as_posix()
                if kind == "scripts":
                    if path.name.startswith("__"):
                        continue
                    if path.suffix.lower() not in SCRIPT_EXTENSIONS:
                        continue
                elif kind == "examples":
                    if path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                elif kind == "references":
                    # examples belong to examples view, not references view
                    if "/examples/" in rel or rel.endswith("/examples"):
                        continue
                paths.add(rel)
        return sorted(paths)[: self.max_list_items]

    def read_resource(
        self,
        spec: SkillSpec,
        kind: ResourceKind,
        relative_path: str,
        *,
        max_chars: int = 12000,
        binary: bool = False,
    ) -> tuple[bool, str]:
        if not relative_path:
            listing = self.list_resources(spec, kind)
            if not listing:
                return True, f"[{spec.name}] 未发现 {kind} 资源。"
            items = "\n".join(f"- {p}" for p in listing)
            return True, f"[{spec.name}] 可读取 {kind} 资源:\n{items}"

        target = (spec.root_dir / relative_path).resolve()
        if not target.exists() or not target.is_file():
            return False, f"[{spec.name}] {kind} 资源不存在: {relative_path}"

        allowed = any(
            self._ensure_within_root(root, target)
            for root in self._kind_roots(spec, kind)
            if root.exists()
        )
        if not allowed:
            return False, f"[{spec.name}] 路径不在 {kind} 允许范围内: {relative_path}"

        rel = target.relative_to(spec.root_dir).as_posix()
        if binary:
            data = target.read_bytes()
            encoded = base64.b64encode(data).decode("ascii")
            limit = max(2000, min(max_chars, self.max_output_chars))
            encoded = self._trim_text(encoded, limit)
            return True, f"[{spec.name}] {kind} 资源(base64): {rel}\nsize={len(data)}\n\n{encoded}"

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False, f"[{spec.name}] {kind} 资源为二进制文件，请使用 binary=true: {rel}"

        limit = max(2000, min(max_chars, self.max_output_chars))
        text = self._trim_text(content, limit)
        return True, f"[{spec.name}] {kind} 资源: {rel}\n\n{text}"

    async def run_script(
        self,
        spec: SkillSpec,
        script_path: str,
        *,
        script_args: str = "",
        timeout_sec: int = 120,
    ) -> str:
        scripts_root = spec.root_dir / "scripts"
        if not script_path:
            scripts = self.list_resources(spec, "scripts")
            if not scripts:
                return f"[{spec.name}] 未发现可执行脚本。"
            items = "\n".join(f"- {item}" for item in scripts)
            return f"[{spec.name}] 可执行脚本:\n{items}"

        target = (spec.root_dir / script_path).resolve()
        if not target.exists() or not target.is_file():
            return f"[{spec.name}] 脚本不存在: {script_path}"
        if not self._ensure_within_root(scripts_root, target):
            return f"[{spec.name}] 仅允许执行 scripts 目录中的脚本: {script_path}"

        suffix = target.suffix.lower()
        if suffix == ".py":
            command = [sys.executable, str(target)]
        elif suffix in {".sh", ".bash"}:
            command = ["bash", str(target)]
        elif suffix in {".js", ".mjs", ".cjs"}:
            command = ["node", str(target)]
        else:
            return f"[{spec.name}] 不支持的脚本类型: {suffix}"

        extra_args = shlex.split(script_args) if script_args.strip() else []
        if len(extra_args) > 50:
            return f"[{spec.name}] 参数过多，最多允许 50 个。"

        timeout = max(5, min(timeout_sec, 600))
        process = await asyncio.create_subprocess_exec(
            *command,
            *extra_args,
            cwd=str(spec.root_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return f"[{spec.name}] 脚本执行超时（>{timeout}s）: {script_path}"

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        result = (
            f"[{spec.name}] 脚本执行完成: {target.relative_to(spec.root_dir).as_posix()}\n"
            f"exit_code={process.returncode}\n\n"
            f"stdout:\n{self._trim_text(stdout_text or '(empty)', self.max_output_chars)}\n\n"
            f"stderr:\n{self._trim_text(stderr_text or '(empty)', self.max_output_chars)}"
        )
        return result
