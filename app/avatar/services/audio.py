"""
Audio processing module.
Manages audio buffer and coordinates with ASR service.
"""

import base64
import asyncio

from app.avatar.services.asr import IatClient
from app.infra.logging import get_logger

logger = get_logger(__name__)


class AudioHandler:
    """Audio handler for buffering and speech recognition."""

    # Audio parameter constants
    SAMPLE_RATE = 16000  # Sample rate 16kHz
    CHUNK_SIZE = 1280  # Chunk size 1280 bytes = 40ms @ 16kHz
    MIN_AUDIO_LENGTH = 1600  # Minimum audio length = 0.1 seconds

    def __init__(self):
        """Initialize audio handler with ASR client and buffer."""
        self.iat_client = IatClient()
        self.audio_buffer = bytearray()

    def add_chunk_base64(self, audio_b64: str):
        """
        Add base64-encoded audio chunk to buffer.

        Args:
            audio_b64: Base64-encoded PCM audio data

        Raises:
            RuntimeError: If audio decoding fails
        """
        try:
            pcm_bytes = base64.b64decode(audio_b64)
            self.audio_buffer.extend(pcm_bytes)
        except Exception as e:
            raise RuntimeError(f"Failed to decode audio data: {e}")

    def clear(self):
        """Clear the audio buffer."""
        self.audio_buffer.clear()

    def is_valid(self) -> bool:
        """
        Check if audio buffer has enough data to be valid.

        Returns:
            bool: True if buffer length >= minimum required
        """
        return len(self.audio_buffer) >= self.MIN_AUDIO_LENGTH

    def get_duration(self) -> float:
        """
        Get audio duration in seconds.

        Returns:
            float: Duration in seconds
        """
        sample_count = len(self.audio_buffer) // 2  # 16-bit = 2 bytes per sample
        return sample_count / self.SAMPLE_RATE

    async def recognize(self) -> str:
        """
        Perform speech recognition on audio buffer.

        Returns:
            str: Recognized text (empty if audio too short)

        Raises:
            RuntimeError: If recognition fails
        """
        if not self.is_valid():
            logger.warning("Audio too short, skipping recognition")
            return ""

        logger.info(f"Starting recognition: {len(self.audio_buffer)} bytes, {self.get_duration():.2f}s")

        # Create queue for streaming
        audio_queue = asyncio.Queue()

        # Split audio into chunks and queue them
        chunk_count = 0
        for i in range(0, len(self.audio_buffer), self.CHUNK_SIZE):
            chunk = bytes(self.audio_buffer[i:i + self.CHUNK_SIZE])
            await audio_queue.put(chunk)
            chunk_count += 1

        logger.debug(f"Audio split into {chunk_count} chunks")

        # Send end signal
        await audio_queue.put(None)

        # Perform recognition
        text = await self.iat_client.recognize_stream(audio_queue)

        if text:
            logger.info(f"Recognition result: {text}")
        else:
            logger.warning("No valid speech recognized")

        return text
