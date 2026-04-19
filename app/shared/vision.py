"""视觉服务：图片分析（Spark OCR + GLM-4V 双模式）。

供 chat、avatar 等需要图片理解的模块共享。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.infra.logging import get_logger
from app.shared.file_service import resolve_uploaded_image_path
from app.shared.spark_image import spark_image_service

logger = get_logger(__name__)


class VisionService:
    """图片分析服务，支持 Spark OCR 和 GLM-4V 双模式。"""

    def __init__(self, glm_vision_llm) -> None:
        self.glm_vision_llm = glm_vision_llm

    async def analyze_images(self, image_urls: list[str], question: str) -> dict:
        """分析图片，优先 Spark 模式，失败时降级到 GLM-4V。"""
        if spark_image_service.configured and image_urls:
            spark_results: list[str] = []
            spark_ok = True
            for url in image_urls:
                image_path = resolve_uploaded_image_path(url)
                if not image_path:
                    spark_ok = False
                    break
                try:
                    image_bytes = image_path.read_bytes()
                    result = await spark_image_service.analyze(image_bytes, question)
                    if result:
                        spark_results.append(result)
                    else:
                        spark_ok = False
                        break
                except Exception as exc:
                    logger.warning("[VisionService] spark failed, fallback to glm: %s", exc)
                    spark_ok = False
                    break

            if spark_ok and spark_results:
                combined = "\n\n".join(spark_results) if len(spark_results) > 1 else spark_results[0]
                return {
                    "success": True,
                    "mode": "spark",
                    "analysis_text": combined,
                    "messages": None,
                    "error": None,
                }

        content_blocks: list[dict] = [{"type": "text", "text": question or "请描述这些图片"}]
        for url in image_urls:
            content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        response = await self.glm_vision_llm.ainvoke([HumanMessage(content=content_blocks)])
        return {
            "success": True,
            "mode": "glm",
            "analysis_text": response.content if isinstance(response.content, str) else str(response.content),
            "messages": [SystemMessage(content=""), response],
            "error": None,
        }


def build_vision_service(glm_vision_llm):
    """工厂函数：创建 VisionService 实例。"""
    return VisionService(glm_vision_llm)