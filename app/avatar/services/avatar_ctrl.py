"""
Avatar control module.
Manages WebSocket connection to Xfyun avatar service and controls speech synthesis.
"""

import json
import uuid
import asyncio
import websockets

from app.config import AVATAR_URL, AVATAR_APP_ID, AVATAR_API_KEY, AVATAR_API_SECRET, ANCHOR_ID, VCN
from app.infra.logging import get_logger
from app.avatar.services import xfyun_auth

logger = get_logger(__name__)


class AvatarController:
    """Xfyun virtual human controller."""

    MAX_RETRIES = 3  # Maximum retry attempts
    RETRY_DELAY = 0.5  # Retry delay in seconds
    KEEPALIVE_INTERVAL = 10  # Heartbeat interval in seconds

    def __init__(self):
        """Initialize avatar controller."""
        self.ws = None
        self.is_ready = False
        self.is_speaking = False
        self.sentence_queue = asyncio.Queue()
        self._playback_task = None
        self._keepalive_task = None
        self._on_reconnect_callback = None
        self._last_stream_info = None
        self._event_callback = None

    @property
    def _ws_closed(self) -> bool:
        """检查 WebSocket 是否已关闭（兼容 websockets 12+ / 16+）"""
        if self.ws is None:
            return True
        # websockets 16+ 使用 state 属性
        if hasattr(self.ws, 'state'):
            from websockets.protocol import State
            return self.ws.state != State.OPEN
        # 旧版使用 closed 属性
        return getattr(self.ws, 'closed', True)

    async def connect(self, on_reconnect_callback=None):
        """
        Connect to avatar service.

        Args:
            on_reconnect_callback: Async callback after reconnection with signature async def callback(stream_info)

        Raises:
            RuntimeError: If connection fails
        """
        self._on_reconnect_callback = on_reconnect_callback

        try:
            auth_url = xfyun_auth.assemble_auth_url(
                AVATAR_URL, 'GET', AVATAR_API_KEY, AVATAR_API_SECRET
            )
            self.ws = await websockets.connect(auth_url)

            # Send start message
            start_msg = {
                "header": {
                    "app_id": AVATAR_APP_ID,
                    "request_id": str(uuid.uuid4()),
                    "ctrl": "start"
                },
                "parameter": {
                    "tts": {"vcn": VCN},
                    "avatar": {
                        "stream": {"protocol": "xrtc"},
                        "avatar_id": ANCHOR_ID,
                        "width": 720,
                        "height": 1280
                    }
                }
            }
            await self.ws.send(json.dumps(start_msg))
            logger.info("Avatar service connected")

            # Start heartbeat keepalive task
            if self._keepalive_task is None or self._keepalive_task.done():
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        except Exception as e:
            logger.error(f"Failed to connect to avatar service: {e}")
            raise RuntimeError(f"Failed to connect to avatar service: {e}")

    async def receive_messages(self, callback):
        """
        Receive messages from avatar service.

        Args:
            callback: Async callback with signature async def callback(event_type, data)

        Raises:
            RuntimeError: If receiving messages fails
        """
        if not self.ws:
            raise RuntimeError("Avatar not connected")

        self._event_callback = callback

        try:
            logger.debug("Starting to listen for avatar messages...")
            async for message in self.ws:
                data = json.loads(message)
                logger.debug(f"Received avatar message: {data.get('header', {})}")

                if data['header']['code'] != 0:
                    logger.error(f"Avatar error: {data}")
                    continue

                payload = data.get('payload', {})
                if 'avatar' not in payload:
                    continue

                avatar_data = payload['avatar']
                event_type = avatar_data.get('event_type')

                if event_type == 'stream_info':
                    self.is_ready = True
                    self._last_stream_info = avatar_data
                    await callback('stream_info', avatar_data)
                    logger.info(f"Avatar video stream ready: {avatar_data.get('stream_url')}")

                elif event_type == 'tts_start':
                    self.is_speaking = True
                    logger.debug("Avatar started speaking")

                elif event_type == 'tts_end':
                    self.is_speaking = False
                    logger.debug("Avatar finished speaking")

            logger.warning("Avatar message loop exited normally (connection closed)")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Avatar connection closed: {e}")
        except Exception as e:
            logger.error(f"Failed to receive avatar messages: {e}", exc_info=True)
            raise RuntimeError(f"Failed to receive avatar messages: {e}")

    async def speak(self, text: str):
        """
        Queue text for avatar to speak (non-blocking).

        Args:
            text: Text to speak
        """
        if not text:
            logger.warning("Empty text, skipping speech")
            return

        # Add to queue (even if not ready, wait for reconnection)
        await self.sentence_queue.put(text)
        logger.debug(f"Sentence queued: {text[:30]}... (queue size: {self.sentence_queue.qsize()})")

        # If not ready, wait for reconnection
        if not self.is_ready:
            logger.debug("Avatar not ready, sentence queued for later")
            return

        # Start queue processor if not running
        if self._playback_task is None or self._playback_task.done():
            self._playback_task = asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        """Process sentence queue sequentially with retry mechanism."""
        logger.info("Starting to process sentence queue")

        while not self.sentence_queue.empty():
            sentence = await self.sentence_queue.get()
            success = await self._speak_with_retry(sentence)

            if not success:
                logger.error(f"Sentence failed after {self.MAX_RETRIES} retries: {sentence[:30]}...")
                continue

            # 等待一小段时间，让讯飞服务开始处理
            await asyncio.sleep(0.5)
            
            # 如果讯飞发了 tts_start，等待 tts_end
            if self.is_speaking:
                logger.debug(f"Avatar started speaking: {sentence[:30]}...")
                wait_end_timeout = 300  # 300 * 0.1 = 30 seconds
                while self.is_speaking and wait_end_timeout > 0:
                    await asyncio.sleep(0.1)
                    wait_end_timeout -= 1
                
                if self.is_speaking:
                    logger.warning(f"Avatar speech timeout (30s), forcing end: {sentence[:30]}...")
                    self.is_speaking = False
                
                logger.debug(f"Sentence completed: {sentence[:30]}...")
            else:
                # 讯飞没发 tts_start，直接继续（可能在后台播报）
                logger.debug(f"Sentence sent (no tts_start): {sentence[:30]}...")

        logger.info("Sentence queue processing completed")

    async def _speak_with_retry(self, text: str) -> bool:
        """
        Speak with retry mechanism (internal method).

        Args:
            text: Text to speak

        Returns:
            bool: True if successful
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                await self._speak_immediate(text)
                return True
            except Exception as e:
                logger.warning(f"Speech failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY)

        return False

    async def _speak_immediate(self, text: str):
        """
        Send speech command immediately (internal method with connection check).

        Args:
            text: Text to speak

        Raises:
            RuntimeError: If sending speech command fails
        """
        # Check connection, reconnect if needed
        if not self.ws or self._ws_closed:
            logger.warning("Avatar connection lost, attempting reconnection...")
            try:
                # Reset state
                self.is_ready = False

                # Reconnect
                await self.connect(on_reconnect_callback=self._on_reconnect_callback)

                # Restart message receiver
                if self._event_callback:
                    asyncio.create_task(self.receive_messages(self._event_callback))

                # Wait for connection ready (stream_info event)
                retry_count = 0
                max_retries = 40  # Max wait 20 seconds
                while not self.is_ready and retry_count < max_retries:
                    await asyncio.sleep(0.5)
                    retry_count += 1

                if not self.is_ready:
                    raise RuntimeError("Avatar not ready after reconnection")

                logger.info("Avatar reconnected successfully")

                # Notify frontend to update video stream
                if self._on_reconnect_callback and self._last_stream_info:
                    await self._on_reconnect_callback(self._last_stream_info)

                # Restart queue processing if there are pending sentences
                if not self.sentence_queue.empty():
                    logger.info(f"Reconnected, {self.sentence_queue.qsize()} sentences pending")
                    if self._playback_task is None or self._playback_task.done():
                        self._playback_task = asyncio.create_task(self._process_queue())

            except Exception as e:
                raise RuntimeError(f"Avatar reconnection failed: {e}")

        # Send speech command
        text_msg = {
            "header": {
                "app_id": AVATAR_APP_ID,
                "request_id": str(uuid.uuid4()),
                "ctrl": "text_driver"
            },
            "parameter": {
                "tts": {"vcn": VCN},
                "avatar_dispatch": {"interactive_mode": 1}  # Enable interactive mode (gesture linkage)
            },
            "payload": {
                "text": {"content": text}
            }
        }

        try:
            await self.ws.send(json.dumps(text_msg))
            logger.info(f"Avatar speaking: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to send speech command: {e}")
            raise RuntimeError(f"Failed to send speech command: {e}")

    async def stop(self):
        """Stop avatar speech and clear queue."""
        # Clear queue
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Cancel queue processing task
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()

        if not self.ws:
            return

        stop_msg = {
            "header": {
                "app_id": AVATAR_APP_ID,
                "request_id": str(uuid.uuid4()),
                "ctrl": "stop"
            }
        }

        try:
            await self.ws.send(json.dumps(stop_msg))
            self.is_speaking = False
            logger.info("Avatar stopped, queue cleared")
        except Exception as e:
            logger.error(f"Failed to stop avatar: {e}")

    async def close(self):
        """Close avatar connection."""
        # Stop heartbeat task
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()

        if self.ws:
            await self.ws.close()
            logger.info("Avatar connection closed")

    async def _keepalive_loop(self):
        """Heartbeat keepalive loop (using WebSocket ping)."""
        try:
            while True:
                await asyncio.sleep(self.KEEPALIVE_INTERVAL)

                if self.ws and not self._ws_closed:
                    try:
                        # Use native WebSocket ping to keep connection alive
                        pong = await self.ws.ping()
                        await asyncio.wait_for(pong, timeout=10)
                        logger.debug("Heartbeat successful")
                    except asyncio.TimeoutError:
                        logger.warning("Heartbeat timeout, connection may be lost")
                    except Exception as e:
                        logger.warning(f"Heartbeat failed: {e}")
        except asyncio.CancelledError:
            logger.info("Heartbeat task stopped")
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}")
