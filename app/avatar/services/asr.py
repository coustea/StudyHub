"""
Xfyun speech recognition (ASR) client.
Supports real-time streaming speech recognition.
"""

import websockets
import json
import base64
import asyncio

from app.config import ASR_SPARK_APP_ID, ASR_SPARK_API_KEY, ASR_SPARK_API_SECRET, IAT_URL
from app.infra.logging import get_logger
from app.avatar.services import xfyun_auth

logger = get_logger(__name__)


class IatClient:
    """Xfyun real-time speech recognition client."""

    def __init__(self):
        """Initialize the ASR client with authenticated URL."""
        self.auth_url = xfyun_auth.assemble_auth_url(
            IAT_URL, 'GET', ASR_SPARK_API_KEY, ASR_SPARK_API_SECRET
        )

    async def recognize_stream(self, audio_queue):
        """
        Perform streaming speech recognition on audio data.

        Args:
            audio_queue: asyncio.Queue containing audio chunks (bytes)

        Returns:
            str: Recognized text

        Raises:
            RuntimeError: If recognition fails
        """
        result_text = ""

        try:
            async with websockets.connect(self.auth_url) as ws:
                # Send start frame
                start_params = {
                    "common": {"app_id": ASR_SPARK_APP_ID},
                    "business": {
                        "language": "zh_cn",
                        "domain": "iat",
                        "accent": "mandarin",
                        "vad_eos": 1000,  # VAD end silence duration (ms)
                        "ptt": 1,
                        "pd": "0",
                        "nunum": 0,
                        "dwa": "wpgs"
                    },
                    "data": {
                        "status": 0,  # 0=first frame
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": ""
                    }
                }
                await ws.send(json.dumps(start_params))

                # Start result receiver task
                recv_task = asyncio.create_task(self._receive_results(ws))

                # Send audio chunks
                while True:
                    try:
                        audio_chunk = await asyncio.wait_for(audio_queue.get(), timeout=1.0)
                        if audio_chunk is None:  # End signal
                            break

                        audio_b64 = base64.b64encode(audio_chunk).decode()
                        frame = {
                            "data": {
                                "status": 1,  # 1=intermediate frame
                                "format": "audio/L16;rate=16000",
                                "encoding": "raw",
                                "audio": audio_b64
                            }
                        }
                        await ws.send(json.dumps(frame))
                    except asyncio.TimeoutError:
                        continue

                # Send end frame
                end_frame = {
                    "data": {
                        "status": 2,  # 2=last frame
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": ""
                    }
                }
                await ws.send(json.dumps(end_frame))

                # Wait for final result
                result_text = await recv_task
                return result_text

        except Exception as e:
            logger.error(f"Speech recognition failed: {e}")
            raise RuntimeError(f"Speech recognition failed: {e}")

    async def _receive_results(self, ws):
        """
        Receive and parse recognition results from WebSocket.

        Args:
            ws: WebSocket connection

        Returns:
            str: Final recognized text

        Raises:
            RuntimeError: If receiving results fails
        """
        result_text = ""

        try:
            async for message in ws:
                data = json.loads(message)
                code = data.get('code', -1)

                if code != 0:
                    error_msg = data.get('message', 'Unknown error')
                    logger.error(f"ASR error: code={code}, message={error_msg}")
                    raise RuntimeError(f"ASR error: {error_msg}")

                result = data.get('data', {}).get('result', {})
                ws_list = result.get('ws', [])

                # Extract words from results
                for ws_item in ws_list:
                    for cw in ws_item.get('cw', []):
                        word = cw.get('w', '')
                        result_text += word

                if ws_list:
                    logger.debug(f"Intermediate result: {result_text}")

                # Check if this is the final result
                if data.get('data', {}).get('status') == 2:
                    logger.info(f"Final recognition result: {result_text}")
                    break

            return result_text

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to receive recognition results: {e}")
            raise RuntimeError(f"Failed to receive recognition results: {e}")
