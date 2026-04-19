"""JSON 解析辅助工具（不使用正则）。

本模块用于处理“模型输出 JSON 结构化结果”的解析与兼容：
- 优先直接 json.loads
- 兼容常见的 Markdown code fence（```json ...```），用行级过滤去掉围栏
- 兼容模型在 JSON 前后夹杂少量说明文字：使用 JSONDecoder.raw_decode 扫描解析首个 JSON 值

注意：本模块刻意不使用正则，避免通过 regex “抠 JSON”。
"""

from __future__ import annotations

import json
from typing import Any


def strip_markdown_code_fences(text: str) -> str:
    """去掉 Markdown code fence（不使用正则）。"""
    if not text:
        return ""
    raw = text.strip()
    if not raw.startswith("```"):
        return raw
    # 兼容 ```json / ``` / ```md 等任意 fence 标记：只去掉以 ``` 开头的行
    lines = [line for line in raw.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def parse_first_json_value(text: str) -> Any:
    """从文本中解析出第一个 JSON 值（dict/list/str/number/bool/null）。

    不使用正则。解析策略：
    1) 去除 code fence
    2) 尝试 json.loads（要求整体即 JSON）
    3) 使用 JSONDecoder.raw_decode 扫描第一个 '{' / '[' 起点并解析
    """
    cleaned = strip_markdown_code_fences(text)
    if not cleaned:
        raise json.JSONDecodeError("empty input", "", 0)

    # 先尝试“整体就是 JSON”
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    s = cleaned.strip()
    # 扫描潜在 JSON 起点（对象/数组）。不解析标量起点是因为多数结构化输出为对象/数组。
    candidates: list[int] = []
    idx = s.find("{")
    while idx != -1:
        candidates.append(idx)
        idx = s.find("{", idx + 1)
    idx = s.find("[")
    while idx != -1:
        candidates.append(idx)
        idx = s.find("[", idx + 1)

    for start in sorted(set(candidates)):
        try:
            value, _end = decoder.raw_decode(s[start:])
            return value
        except json.JSONDecodeError:
            continue

    # 最后一次：让异常信息更贴近原始输入
    raise json.JSONDecodeError("no JSON value found", s, 0)


def parse_first_json_object(text: str) -> dict[str, Any]:
    """解析并保证返回 dict。"""
    value = parse_first_json_value(text)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object(dict), got {type(value).__name__}")
    return value


def preview_for_log(value: Any, max_len: int = 500) -> str:
    """用于日志的输出摘要，避免日志过长。"""
    try:
        dumped = json.dumps(value, ensure_ascii=False)
    except Exception:
        dumped = str(value)
    dumped = dumped.replace("\n", " ")
    return dumped[:max_len] + ("..." if len(dumped) > max_len else "")

