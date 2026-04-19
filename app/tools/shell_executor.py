"""
Shell 命令执行工具。

ShellExecutor 类封装了所有 shell 执行策略：
- execute: 通用型异步执行，黑名单过滤 + 工作目录限制 + 超时控制
- execute_sync: 同步版本的通用执行
- safe_execute: 严格型执行，白名单放行，用于受限环境

对外注册 3 个 @tool：execute_shell、execute_shell_sync、safe_shell
"""

import asyncio
import re
import shlex
import subprocess
from pathlib import Path

from langchain.tools import tool

from app.shared.paths import SERVER_DIR, WORKPLACE_DIR
from app.tools.registry import register


class ShellExecutor:
    """Shell 命令执行器，内置安全策略与输出格式化。"""

    # ── 黑名单模式配置 ──────────────────────────────────────────

    BLOCKED_PATTERNS: list[re.Pattern] = [
        re.compile(r"\brm\s+(-\w*r\w*f\w*|--force)\s+/", re.IGNORECASE),
        re.compile(r"\bmkfs\b", re.IGNORECASE),
        re.compile(r"\bdd\s+if=.*of=/dev/", re.IGNORECASE),
        re.compile(r">\s*/dev/sd", re.IGNORECASE),
        re.compile(r"\bchmod\s+(-R\s+)?000\b"),
        re.compile(r"\bchown\s+(-R\s+)?root\b"),
        re.compile(r"\biptables\b", re.IGNORECASE),
        re.compile(r"\bsystemctl\s+(stop|disable|mask)\b", re.IGNORECASE),
        re.compile(r"\bshutdown\b", re.IGNORECASE),
        re.compile(r"\breboot\b", re.IGNORECASE),
        re.compile(r"\bcurl\s+.*\|\s*sh", re.IGNORECASE),
        re.compile(r"\bwget\s+.*\|\s*sh", re.IGNORECASE),
        re.compile(r"\bpip\s+uninstall\s+-y\s+(langchain|fastapi|sqlmodel)", re.IGNORECASE),
    ]

    ALLOWED_BASE_DIRS: list[Path] = [SERVER_DIR, WORKPLACE_DIR]

    MAX_OUTPUT_LENGTH = 50_000
    DEFAULT_TIMEOUT = 30
    MAX_TIMEOUT = 120

    # ── 白名单模式配置 ──────────────────────────────────────────

    ALLOWED_COMMANDS = {
        "ls", "pwd", "echo", "cat", "grep", "find",
        "head", "tail", "python3", "node",
    }

    BLOCKED_KEYWORDS = {
        "rm", "shutdown", "reboot", "mkfs", "dd",
        "chmod", "chown", "kill", "pkill", "sudo", "su",
    }

    DANGEROUS_SYMBOLS = {
        ";", "&&", "||", "|", "`", "$(", ">", ">>", "<",
    }

    # ── 安全检查 ────────────────────────────────────────────────

    def check_blacklist(self, command: str) -> tuple[bool, str]:
        """黑名单模式：匹配到危险模式则拒绝。"""
        for pattern in self.BLOCKED_PATTERNS:
            if pattern.search(command):
                return False, f"危险命令被拦截: 匹配规则 '{pattern.pattern}'"
        return True, ""

    def check_whitelist(self, command: str) -> tuple[bool, str]:
        """白名单模式：仅允许预定义命令，禁止管道和重定向。"""
        for symbol in self.DANGEROUS_SYMBOLS:
            if symbol in command:
                return False, f"包含危险符号: {symbol}"

        try:
            parts = shlex.split(command)
        except Exception:
            return False, "命令解析失败"

        if not parts:
            return False, "空命令"

        if parts[0] not in self.ALLOWED_COMMANDS:
            return False, f"命令不在白名单: {parts[0]}"

        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in parts:
                return False, f"包含黑名单命令: {keyword}"

        return True, "安全"

    def resolve_workdir(self, workdir: str) -> Path | str:
        """解析工作目录，不合法时返回错误字符串。"""
        if not workdir:
            return SERVER_DIR
        try:
            resolved = Path(workdir).resolve()
            if any(str(resolved).startswith(str(base.resolve())) for base in self.ALLOWED_BASE_DIRS):
                return resolved
        except (OSError, ValueError):
            pass
        return f"❌ 工作目录被拒绝: {workdir}（仅允许项目目录）"

    # ── 输出格式化 ──────────────────────────────────────────────

    def _format_output(self, stdout: str, stderr: str, returncode: int) -> str:
        """统一格式化命令输出。"""
        parts = []
        if stdout.strip():
            parts.append(stdout.strip())
        if stderr.strip():
            parts.append(f"[stderr]\n{stderr.strip()}")

        output = "\n".join(parts) if parts else "(无输出)"
        output += f"\n\n[退出码: {returncode}]"

        if len(output) > self.MAX_OUTPUT_LENGTH:
            output = output[:self.MAX_OUTPUT_LENGTH] + f"\n\n... (输出已截断，共 {len(output)} 字符)"
        return output

    # ── 执行方法 ────────────────────────────────────────────────

    async def execute(self, command: str, workdir: str = "", timeout: int = DEFAULT_TIMEOUT) -> str:
        """异步执行 shell 命令（黑名单模式）。"""
        is_safe, reason = self.check_blacklist(command)
        if not is_safe:
            return f"❌ 命令被拒绝: {reason}"

        cwd = self.resolve_workdir(workdir)
        if isinstance(cwd, str):
            return cwd

        timeout = min(timeout, self.MAX_TIMEOUT)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            return self._format_output(
                stdout_bytes.decode("utf-8", errors="replace"),
                stderr_bytes.decode("utf-8", errors="replace"),
                proc.returncode,
            )

        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return f"❌ 命令超时 ({timeout}秒): {command}"
        except Exception as e:
            return f"❌ 执行失败: {type(e).__name__}: {e}"

    def execute_sync(self, command: str, workdir: str = "", timeout: int = DEFAULT_TIMEOUT) -> str:
        """同步执行 shell 命令（黑名单模式）。"""
        is_safe, reason = self.check_blacklist(command)
        if not is_safe:
            return f"❌ 命令被拒绝: {reason}"

        cwd = self.resolve_workdir(workdir)
        if isinstance(cwd, str):
            return cwd

        timeout = min(timeout, self.MAX_TIMEOUT)

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=str(cwd), timeout=timeout,
            )
            return self._format_output(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            return f"❌ 命令超时 ({timeout}秒): {command}"
        except Exception as e:
            return f"❌ 执行失败: {type(e).__name__}: {e}"

    def safe_execute(self, command: str) -> str:
        """白名单模式执行，仅允许基础命令。"""
        is_safe, message = self.check_whitelist(command)
        if not is_safe:
            return f" 拒绝执行: {message}"

        try:
            result = subprocess.run(
                shlex.split(command), capture_output=True, text=True,
                timeout=5, cwd=str(SERVER_DIR),
            )
            if result.returncode != 0:
                return f"执行失败:\n{result.stderr.strip()}"
            return result.stdout.strip() or "执行成功（无输出）"

        except subprocess.TimeoutExpired:
            return "命令执行超时"
        except Exception as e:
            return f"执行异常: {str(e)}"


# ──────────────────────────────────────────────────────────────
# 单例 + @tool 注册
# ──────────────────────────────────────────────────────────────

_shell = ShellExecutor()


@tool("execute_shell")
async def execute_shell(command: str, workdir: str = "", timeout: int = 30) -> str:
    """安全执行 shell 命令，捕获 stdout 和 stderr（黑名单模式，支持自定义工作目录和超时）。"""
    return await _shell.execute(command, workdir, timeout)


@tool("execute_shell_sync")
def execute_shell_sync(command: str, workdir: str = "", timeout: int = 30) -> str:
    """同步版本的 shell 命令执行（用于非异步上下文，黑名单模式）。"""
    return _shell.execute_sync(command, workdir, timeout)


@tool("safe_shell", description="安全执行受限的Shell命令，仅支持白名单命令")
def safe_shell(command: str) -> str:
    """执行安全Shell命令（白名单模式，仅允许 ls/pwd/cat/grep/find 等基础命令）。"""
    return _shell.safe_execute(command)


# 自注册到工具注册表
register(execute_shell)
register(execute_shell_sync)
register(safe_shell)
