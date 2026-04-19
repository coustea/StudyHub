from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.infra.logging import get_logger

logger = get_logger(__name__)


class ImageExplainerAgent:
    def __init__(self) -> None:
        self.name = "ImageExplainerAgent"
        self.agent_dir = Path(__file__).parent

    async def generate_image(
        self,
        topic: str,
        course: str = "",
        major: str = "通用",
        gap: str = "",
        user_profile: dict | None = None,
        shared_memory: dict | None = None,
    ) -> dict[str, Any]:
        profile = user_profile or {}
        memory = shared_memory or {}
        logger.info(
            "[ImageAgent] 开始生成图解资源: topic=%r course=%r has_mindmap=%s",
            topic,
            course,
            "mindmap" in memory,
        )
        figures = [
            {
                "title": f"{topic} 概念全景图",
                "caption": f"帮助 {major or '学习者'} 快速建立 {course or topic} 的知识全貌。",
            },
            {
                "title": f"{topic} 关键流程图解",
                "caption": f"围绕薄弱点“{gap or topic}”拆解关键步骤与触发条件。",
            },
            {
                "title": f"{topic} 易错点对照图",
                "caption": f"结合画像中的易错模式，突出概念边界、异常场景与常见混淆点。",
            },
        ]
        images = [
            self._svg_data_uri(title=item["title"], caption=item["caption"], accent=str(index + 1))
            for index, item in enumerate(figures)
        ]

        # 这里先产出稳定可展示的图解包，后续再把生成逻辑替换成真正的图片模型。
        content_lines = [
            f"# {topic} 图解资源包",
            "",
            f"- 适用课程：{course or topic}",
            f"- 学习短板：{gap or '待进一步确认'}",
            f"- 推荐认知风格适配：{profile.get('cognitive_style') or '图解 + 对比讲解'}",
            "",
            "## 图解使用建议",
        ]
        for item in figures:
            content_lines.extend(
                [
                    f"### {item['title']}",
                    item["caption"],
                    "",
                ]
            )

        if "mindmap" in memory:
            # 如果上游已经给出思维导图，这里补一段“如何联动使用”说明，增强资源之间的串联感。
            content_lines.extend(
                [
                    "## 导图联动建议",
                    "先看思维导图把握结构，再逐张图解理解流程和易错点。",
                    "",
                ]
            )

        result = {
            "success": True,
            "type": "image",
            "title": f"{topic} 图解资源",
            "content": "\n".join(content_lines).strip(),
            "images": images,
            "figures": figures,
            "error": None,
        }
        logger.info("[ImageAgent] 图解资源生成完成: topic=%r image_count=%s", topic, len(images))
        return result

    @staticmethod
    def _svg_data_uri(title: str, caption: str, accent: str) -> str:
        # 使用 SVG data URI 是为了首版无需额外文件存储，也能直接在前端即时预览。
        svg = f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
          <rect width="960" height="540" rx="28" fill="#f8fafc"/>
          <rect x="40" y="40" width="880" height="460" rx="24" fill="#ffffff" stroke="#cbd5e1" stroke-width="4"/>
          <rect x="80" y="90" width="120" height="120" rx="24" fill="#eef2ff"/>
          <text x="140" y="165" text-anchor="middle" font-size="56" font-family="Arial" fill="#4338ca">{accent}</text>
          <text x="240" y="150" font-size="38" font-weight="700" font-family="Arial" fill="#0f172a">{title}</text>
          <text x="240" y="210" font-size="24" font-family="Arial" fill="#475569">{caption}</text>
          <rect x="90" y="280" width="780" height="44" rx="16" fill="#e0e7ff"/>
          <rect x="90" y="344" width="620" height="44" rx="16" fill="#dcfce7"/>
          <rect x="90" y="408" width="700" height="44" rx="16" fill="#fee2e2"/>
        </svg>
        """.strip()
        return f"data:image/svg+xml;charset=UTF-8,{quote(svg)}"
