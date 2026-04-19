from __future__ import annotations

from pathlib import Path
from typing import Any

from app.infra.logging import get_logger

logger = get_logger(__name__)


class VideoLectureAgent:
    def __init__(self) -> None:
        self.name = "VideoLectureAgent"
        self.agent_dir = Path(__file__).parent

    async def generate_video(
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
            "[VideoAgent] 开始生成视频讲解包: topic=%r course=%r has_ppt=%s has_image=%s",
            topic,
            course,
            "ppt" in memory,
            "image" in memory,
        )
        # 首版先稳定产出“视频讲解包”，包括讲解脚本、分镜和字幕，后面再对接真实视频合成。
        scenes = [
            {
                "scene": 1,
                "title": "开场定位学习目标",
                "visual": "标题页 + 学习目标提示卡",
                "narration": f"今天我们聚焦 {topic}，重点解决“{gap or '关键概念理解'}”这一薄弱点。",
                "duration": "20s",
            },
            {
                "scene": 2,
                "title": "核心原理拆解",
                "visual": "调用图解资源逐步解释流程",
                "narration": f"先建立 {course or topic} 的整体结构，再拆解关键流程与触发条件。",
                "duration": "45s",
            },
            {
                "scene": 3,
                "title": "易错点纠偏",
                "visual": "对照图 + 常见错误列表",
                "narration": "把最容易混淆的边界条件单独拿出来讲，帮助你避免重复犯错。",
                "duration": "35s",
            },
            {
                "scene": 4,
                "title": "总结与练习引导",
                "visual": "复盘清单 + 练习题入口",
                "narration": "最后用一个简短总结收束知识，再引导进入题库和实操案例。",
                "duration": "20s",
            },
        ]

        # 字幕直接由分镜配音串联生成，便于后续接 TTS 或数字人服务。
        subtitle = "\n".join(item["narration"] for item in scenes)
        content_lines = [
            f"# {topic} 视频讲解包",
            "",
            f"- 适用课程：{course or topic}",
            f"- 目标学习者：{major or '通用专业'}",
            f"- 画像适配：{profile.get('learning_pace') or '节奏可调'} / {profile.get('cognitive_style') or '图解优先'}",
            "",
            "## 分镜脚本",
        ]
        for item in scenes:
            content_lines.extend(
                [
                    f"### Scene {item['scene']} · {item['title']}",
                    f"- 画面：{item['visual']}",
                    f"- 配音：{item['narration']}",
                    f"- 时长：{item['duration']}",
                    "",
                ]
            )

        result = {
            "success": True,
            "type": "video",
            "title": f"{topic} 视频讲解包",
            "content": "\n".join(content_lines).strip(),
            "videos": [],
            "storyboard": scenes,
            "subtitle": subtitle,
            "error": None,
        }
        logger.info("[VideoAgent] 视频讲解包生成完成: topic=%r scene_count=%s", topic, len(scenes))
        return result
