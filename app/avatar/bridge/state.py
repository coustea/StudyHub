"""
Bridge service state management.
Defines states and message types for avatar WebSocket communication.
"""

from enum import Enum


class BridgeState(Enum):
    """Bridge service state enumeration."""
    IDLE = "idle"                      # Idle
    RECEIVING_AUDIO = "receiving_audio"  # Receiving audio
    RECOGNIZING = "recognizing"        # Recognizing speech
    GENERATING = "generating"          # Generating response
    SPEAKING = "speaking"              # Avatar speaking


class MessageType:
    """Message type constants."""
    # Client → Server
    AUDIO_CHUNK = "audio_chunk"
    AUDIO_END = "audio_end"
    TEXT_INPUT = "text_input"
    STOP_SPEAKING = "stop_speaking"
    CLEAR_HISTORY = "clear_history"

    # Server → Client
    STATUS = "status"
    STREAM_INFO = "stream_info"
    ASR_RESULT = "asr_result"
    USER_MESSAGE = "user_message"
    ASSISTANT_CHUNK = "assistant_chunk"
    ASSISTANT_COMPLETE = "assistant_complete"
    AVATAR_STOPPED = "avatar_stopped"
    ERROR = "error"

    # Additional message types
    START_VAD = "start_vad"
    STOP_VAD = "stop_vad"
    SWITCH_SESSION = "switch_session"
    VAD_STATE = "vad_state"

    # Tool events
    TOOL_CALL_START = "tool_call_start"
    TOOL_RESULT = "tool_result"
    RESOURCE_GENERATED = "resource_generated"
