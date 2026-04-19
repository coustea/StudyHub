"""External image-understanding adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import ssl
from datetime import datetime
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websockets

from app.config import SPARK_VISION_API_KEY, SPARK_VISION_API_SECRET, SPARK_VISION_APPID
from app.infra.logging import get_logger

logger = get_logger(__name__)
_SPARK_IMAGE_URL = "wss://spark-api.cn-huabei-1.xf-yun.com/v2.1/image"


class _WsParam:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = urlparse(base_url).netloc
        self.path = urlparse(base_url).path
        self.base_url = base_url

    def create_url(self) -> str:
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))
        signature_origin = f"host: {self.host}\ndate: {date}\nGET {self.path} HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode(),
            signature_origin.encode(),
            digestmod=hashlib.sha256,
        ).digest()
        signature_b64 = base64.b64encode(signature_sha).decode()
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature_b64}"'
        )
        authorization = base64.b64encode(authorization_origin.encode()).decode()
        params = {"authorization": authorization, "date": date, "host": self.host}
        return f"{self.base_url}?{urlencode(params)}"


class SparkImageService:
    def __init__(self):
        self.appid = SPARK_VISION_APPID
        self.api_key = SPARK_VISION_API_KEY
        self.api_secret = SPARK_VISION_API_SECRET
        if not all([self.appid, self.api_key, self.api_secret]):
            logger.warning("[SparkImage] 凭据未完整配置，图片理解将回退到 GLM")

    @property
    def configured(self) -> bool:
        return bool(self.appid and self.api_key and self.api_secret)

    async def analyze(self, image_bytes: bytes, question: str = "请描述这张图片") -> str:
        if not self.configured:
            raise RuntimeError("Spark Image API 凭据未配置")

        ws_param = _WsParam(self.api_key, self.api_secret, _SPARK_IMAGE_URL)
        url = ws_param.create_url()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        request_body = {
            "header": {"app_id": self.appid},
            "parameter": {"chat": {"domain": "imagev3", "temperature": 0.5, "top_k": 4, "max_tokens": 2028, "auditing": "default"}},
            "payload": {"message": {"text": [{"role": "user", "content": image_b64, "content_type": "image"}, {"role": "user", "content": question}]}},
        }

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        answer = ""
        async with websockets.connect(url, ssl=ssl_ctx, proxy=None) as ws:
            await ws.send(json.dumps(request_body))
            async for raw in ws:
                data = json.loads(raw)
                code = data["header"]["code"]
                if code != 0:
                    raise RuntimeError(f"Spark Image API 错误: code={code}, {data}")
                answer += data["payload"]["choices"]["text"][0]["content"]
                if data["payload"]["choices"]["status"] == 2:
                    break
        return answer


spark_image_service = SparkImageService()
