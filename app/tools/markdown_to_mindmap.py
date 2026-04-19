"""
Markdown → HTML 思维导图工具。

将 Markdown 层级结构转换为基于 markmap 的交互式 HTML 思维导图。
"""

import json
import re

from langchain.tools import tool

from app.tools.file_operator import save_to_workplace
from app.tools.registry import register

# HTML 模板：用 markmap-lib + markmap-view（CDN）渲染真正的思维导图
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; overflow: hidden; }}
    #mindmap {{ width: 100%; height: 100vh; }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <script src="https://cdn.jsdelivr.net/npm/markmap-lib@0.18.12"></script>
  <script src="https://cdn.jsdelivr.net/npm/markmap-view@0.18.12"></script>
</head>
<body>
  <svg id="mindmap"></svg>
  <script>
    const {{ Transformer }} = window.markmap;
    const {{ Markmap }} = window.markmap;
    const transformer = new Transformer();
    const {{ root }} = transformer.transform({md_json});
    Markmap.create("svg#mindmap", {{}}, root);
  </script>
</body>
</html>"""


def _render_markmap_html(markdown_text: str) -> str:
    """用 markmap（CDN）将 Markdown 渲染为真正的思维导图。"""
    title_match = re.search(r"^#\s+(.+)", markdown_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "思维导图"

    md_json = json.dumps(markdown_text, ensure_ascii=False)

    return _HTML_TEMPLATE.format(title=title, md_json=md_json)


@tool("markdown_to_mindmap")
def markdown_to_mindmap(markdown_text: str) -> str:
    """将 Markdown 层级结构转换为 HTML 思维导图，并保存到 workplace/mindmap。"""
    title_match = re.search(r"^#\s+(.+)", markdown_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "思维导图"

    html_content = _render_markmap_html(markdown_text)
    file_path = save_to_workplace("mindmap", title, html_content, "html")
    return json.dumps(
        {
            "file_path": file_path,
            "filePath": file_path,
            "title": title,
        },
        ensure_ascii=False,
    )


# 自注册到工具注册表
register(markdown_to_mindmap)