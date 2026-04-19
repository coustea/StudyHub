"""
多语言代码执行工具。

支持运行以下语言的代码：
- Python (.py)
- C (.c)
- C++ (.cpp, .cc, .cxx)
- Go (.go)
- Java (.java)
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

from langchain.tools import tool

from app.shared.paths import WORKPLACE_DIR
from app.tools.registry import register

# ──────────────────────────────────────────────────────────────
# 语言配置
# ──────────────────────────────────────────────────────────────

LANGUAGE_CONFIG: dict[str, dict] = {
    "python": {
        "ext": ".py",
        "compile_cmd": None,
        "run_cmd": "python3 {file}",
        "timeout": 30,
    },
    "c": {
        "ext": ".c",
        "compile_cmd": "gcc -o {output} {file} -lm -Wall 2>&1",
        "run_cmd": "{output}",
        "timeout": 30,
    },
    "cpp": {
        "ext": ".cpp",
        "compile_cmd": "g++ -o {output} {file} -std=c++17 -Wall 2>&1",
        "run_cmd": "{output}",
        "timeout": 30,
    },
    "go": {
        "ext": ".go",
        "compile_cmd": None,
        "run_cmd": "go run {file}",
        "timeout": 60,
    },
    "java": {
        "ext": ".java",
        "compile_cmd": "javac {file} 2>&1",
        "run_cmd": "java -cp {workdir} {classname}",
        "timeout": 30,
    },
}

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".go": "go",
    ".java": "java",
}

MAX_OUTPUT_LENGTH = 50_000
MAX_CODE_LENGTH = 100_000


def _detect_language(code: str, language: str = "", filepath: str = "") -> str:
    if language and language.lower() in LANGUAGE_CONFIG:
        return language.lower()

    if filepath:
        ext = Path(filepath).suffix.lower()
        if ext in EXT_TO_LANG:
            return EXT_TO_LANG[ext]

    if code.strip().startswith("package "):
        return "java"
    if "func main()" in code or "package main" in code:
        return "go"
    if '#include' in code and 'iostream' in code:
        return "cpp"
    if '#include' in code:
        return "c"

    return "python"


# ──────────────────────────────────────────────────────────────
# @tool 工具函数
# ──────────────────────────────────────────────────────────────

@tool("run_code")
async def run_code(
    code: str,
    language: str = "",
    stdin: str = "",
    timeout: int = 0,
) -> str:
    """运行代码片段，支持 Python、C、C++、Go、Java。

    Args:
        code: 要执行的代码内容
        language: 编程语言（python/c/cpp/go/java），留空则自动检测
        stdin: 标准输入内容（可选）
        timeout: 超时秒数（0 表示使用语言默认值）

    Returns:
        执行结果（stdout + stderr + 退出码）
    """
    lang = _detect_language(code, language)
    config = LANGUAGE_CONFIG[lang]

    if len(code) > MAX_CODE_LENGTH:
        return f"❌ 代码过长: {len(code)} 字符（最大 {MAX_CODE_LENGTH}）"

    exec_timeout = timeout if timeout > 0 else config["timeout"]
    exec_timeout = min(exec_timeout, 120)

    with tempfile.TemporaryDirectory(prefix="agent_run_") as tmpdir:
        tmpdir_path = Path(tmpdir)

        src_file = tmpdir_path / f"main{config['ext']}"
        src_file.write_text(code, encoding="utf-8")

        output_binary = tmpdir_path / "main.out"

        try:
            if config["compile_cmd"]:
                compile_cmd = config["compile_cmd"].format(
                    file=str(src_file),
                    output=str(output_binary),
                    workdir=str(tmpdir_path),
                )
                proc = await asyncio.create_subprocess_shell(
                    compile_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(tmpdir_path),
                )
                compile_out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

                if proc.returncode != 0:
                    compile_msg = compile_out.decode("utf-8", errors="replace")
                    return f"❌ 编译失败 ({lang}):\n{compile_msg}"

            classname = ""
            if lang == "java":
                import re
                match = re.search(r"public\s+class\s+(\w+)", code)
                classname = match.group(1) if match else "Main"

            run_cmd = config["run_cmd"].format(
                file=str(src_file),
                output=str(output_binary),
                workdir=str(tmpdir_path),
                classname=classname,
            )

            proc = await asyncio.create_subprocess_shell(
                run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                cwd=str(tmpdir_path),
            )

            stdin_bytes = stdin.encode("utf-8") if stdin else None
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=exec_timeout,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            parts = [f"语言: {lang}", ""]
            if stdout.strip():
                parts.append(f"--- 输出 ---\n{stdout.strip()}")
            if stderr.strip():
                parts.append(f"--- 错误 ---\n{stderr.strip()}")
            parts.append(f"\n[退出码: {proc.returncode}]")

            result = "\n".join(parts)
            if len(result) > MAX_OUTPUT_LENGTH:
                result = result[:MAX_OUTPUT_LENGTH] + f"\n... (截断，共 {len(result)} 字符)"

            return result

        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return f"❌ 执行超时 ({exec_timeout}秒): {lang}"
        except Exception as e:
            return f"❌ 执行失败: {type(e).__name__}: {e}"


@tool("run_file")
async def run_file(
    filepath: str,
    args: str = "",
    stdin: str = "",
    timeout: int = 0,
) -> str:
    """运行指定路径的代码文件，根据扩展名自动选择编译器/解释器。

    Args:
        filepath: 源代码文件的路径
        args: 命令行参数（空格分隔）
        stdin: 标准输入内容（可选）
        timeout: 超时秒数（0 表示使用语言默认值）

    Returns:
        执行结果
    """
    file_path = Path(filepath)

    if not file_path.exists():
        return f"❌ 文件不存在: {filepath}"

    ext = file_path.suffix.lower()
    if ext not in EXT_TO_LANG:
        return f"❌ 不支持的文件类型: {ext}（支持: {', '.join(EXT_TO_LANG.keys())})"

    lang = EXT_TO_LANG[ext]
    config = LANGUAGE_CONFIG[lang]
    exec_timeout = timeout if timeout > 0 else config["timeout"]
    exec_timeout = min(exec_timeout, 120)

    workdir = file_path.parent
    output_binary = workdir / (file_path.stem + ".out")

    try:
        if config["compile_cmd"]:
            compile_cmd = config["compile_cmd"].format(
                file=str(file_path),
                output=str(output_binary),
                workdir=str(workdir),
            )
            proc = await asyncio.create_subprocess_shell(
                compile_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workdir),
            )
            compile_out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                return f"❌ 编译失败 ({lang}):\n{compile_out.decode('utf-8', errors='replace')}"

        classname = ""
        if lang == "java":
            import re
            content = file_path.read_text(encoding="utf-8")
            match = re.search(r"public\s+class\s+(\w+)", content)
            classname = match.group(1) if match else file_path.stem

        run_cmd = config["run_cmd"].format(
            file=str(file_path),
            output=str(output_binary),
            workdir=str(workdir),
            classname=classname,
        )
        if args:
            run_cmd += f" {args}"

        proc = await asyncio.create_subprocess_shell(
            run_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            cwd=str(workdir),
        )

        stdin_bytes = stdin.encode("utf-8") if stdin else None
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes),
            timeout=exec_timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        parts = [f"文件: {filepath} ({lang})", ""]
        if stdout.strip():
            parts.append(f"--- 输出 ---\n{stdout.strip()}")
        if stderr.strip():
            parts.append(f"--- 错误 ---\n{stderr.strip()}")
        parts.append(f"\n[退出码: {proc.returncode}]")

        result = "\n".join(parts)
        if len(result) > MAX_OUTPUT_LENGTH:
            result = result[:MAX_OUTPUT_LENGTH] + f"\n... (截断，共 {len(result)} 字符)"

        return result

    except asyncio.TimeoutError:
        return f"❌ 执行超时 ({exec_timeout}秒): {filepath}"
    except Exception as e:
        return f"❌ 执行失败: {type(e).__name__}: {e}"


# 自注册到工具注册表
register(run_code)
register(run_file)