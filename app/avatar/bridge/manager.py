# -*- coding: utf-8 -*-
"""
AvatarBridgeManager — 管理每个用户的 RealtimeBridge 实例

在 Avatar Bridge 独立进程 (:8765) 中运行，
管理 per-user 的 WebSocket 连接、ASR、AvatarController 等。
"""

import asyncio
import json
from typing import Optional

from app.infra.logging import get_logger

logger = get_logger(__name__)


class RealtimeBridge:
    """per-user 的实时桥接：管理 WS 连接、ASR、AvatarAgent、视频流"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.session_id: str = ""
        self.frontend_ws = None  # WebSocket 连接
        self.is_listening = False
        self.current_audio_queue: Optional[asyncio.Queue] = None

        # 延迟初始化的服务
        self._avatar_controller = None
        self._asr_loop_task = None

        # VAD 状态
        self._vad_eos = 1000
        self._consecutive_empty = 0
        self._empty_rate = 0.0
        self._round_metrics: list[dict] = []

    async def _ensure_avatar_controller(self):
        if self._avatar_controller is None:
            from app.avatar.services.avatar_ctrl import AvatarController
            self._avatar_controller = AvatarController()
            await self._avatar_controller.connect(
                on_reconnect_callback=self._on_avatar_reconnect
            )
            # 启动消息接收
            asyncio.create_task(
                self._avatar_controller.receive_messages(self._on_avatar_event)
            )
            # 等待就绪
            for _ in range(40):  # 最多等 20 秒
                if self._avatar_controller.is_ready:
                    break
                await asyncio.sleep(0.5)

    async def _on_avatar_reconnect(self, stream_info: dict):
        """Avatar 重连回调 — 通知前端更新视频流"""
        await self._send_to_frontend({
            "type": "stream_info",
            "data": stream_info,
        })

    async def _on_avatar_event(self, event_type: str, data: dict):
        """Avatar 事件回调"""
        if event_type == "stream_info":
            await self._send_to_frontend({
                "type": "stream_info",
                "data": data,
            })

    async def handle_frontend(self, ws):
        """处理前端 WebSocket 连接"""
        self.frontend_ws = ws

        # 确保 AvatarController 已连接（失败不阻断文本对话）
        try:
            await self._ensure_avatar_controller()
        except Exception as e:
            logger.warning("[Bridge] AvatarController 连接失败（文本对话仍可用）: %s", e)

        # 发送初始流信息
        if self._avatar_controller and self._avatar_controller._last_stream_info:
            await self._send_to_frontend({
                "type": "stream_info",
                "data": self._avatar_controller._last_stream_info,
            })

        try:
            while True:
                try:
                    message = await ws.receive_text()
                    data = json.loads(message)
                    await self._route_message(data)
                except Exception as e:
                    logger.error("[Bridge] 消息处理错误: %s", e)
                    await self._send_to_frontend({"type": "error", "content": str(e)})
        except Exception as e:
            logger.error("[Bridge] handle_frontend 异常: %s", e, exc_info=True)
        finally:
            self.frontend_ws = None

    async def _route_message(self, data: dict):
        """消息路由"""
        from app.avatar.bridge.state import MessageType

        msg_type = data.get("type", "")

        if msg_type == MessageType.AUDIO_CHUNK:
            await self._handle_audio_chunk(data)
        elif msg_type == MessageType.AUDIO_END:
            await self._handle_audio_end()
        elif msg_type == MessageType.TEXT_INPUT:
            await self._handle_text_input(data)
        elif msg_type == MessageType.STOP_SPEAKING:
            await self._handle_stop_speaking()
        elif msg_type == MessageType.CLEAR_HISTORY:
            pass  # TODO
        elif msg_type == "start_vad":
            await self._handle_start_vad()
        elif msg_type == "stop_vad":
            await self._handle_stop_vad()
        elif msg_type == "switch_session":
            self.session_id = data.get("session_id", "")

    async def _handle_audio_chunk(self, data: dict):
        """处理音频块"""
        import base64
        audio_b64 = data.get("audio", "")
        if not audio_b64 or not self.current_audio_queue:
            return
        pcm_bytes = base64.b64decode(audio_b64)
        # 分割为 1280 字节块（40ms @ 16kHz）
        import time
        for i in range(0, len(pcm_bytes), 1280):
            chunk = pcm_bytes[i:i + 1280]
            await self.current_audio_queue.put((time.monotonic(), chunk))

    async def _handle_audio_end(self):
        """音频输入结束"""
        if self.current_audio_queue:
            await self.current_audio_queue.put(None)

    async def _handle_text_input(self, data: dict):
        """处理文本输入 — 通过 AvatarAgent 生成回复"""
        text = data.get("text", "")
        if not text:
            return
        await self._handle_user_text(text, source="text")

    async def _handle_stop_speaking(self):
        """停止说话"""
        if self._avatar_controller:
            await self._avatar_controller.stop()

    async def _handle_start_vad(self):
        """开始语音活动检测"""
        self.is_listening = True
        self.current_audio_queue = asyncio.Queue()
        if self._asr_loop_task is None or self._asr_loop_task.done():
            self._asr_loop_task = asyncio.create_task(self._continuous_listen_loop())
        await self._send_to_frontend({"type": "vad_state", "data": {"listening": True}})

    async def _handle_stop_vad(self):
        """停止语音活动检测"""
        self.is_listening = False
        if self.current_audio_queue:
            await self.current_audio_queue.put(None)
        if self._asr_loop_task and not self._asr_loop_task.done():
            self._asr_loop_task.cancel()
        await self._send_to_frontend({"type": "vad_state", "data": {"listening": False}})

    async def _continuous_listen_loop(self):
        """持续监听循环"""
        from app.avatar.services.asr import IatClient
        from app.avatar.services.xfyun_auth import assemble_auth_url
        from app.config import ASR_SPARK_APP_ID, ASR_SPARK_API_KEY, ASR_SPARK_API_SECRET, IAT_URL
        import websockets, json, base64, time

        while self.is_listening:
            try:
                await self._single_recognition_round()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Bridge] ASR 轮次失败: %s", e)
                await asyncio.sleep(0.5)

    async def _single_recognition_round(self):
        """单次 ASR 识别轮次"""
        import websockets, json, base64, time, asyncio
        from app.avatar.services.xfyun_auth import assemble_auth_url
        from app.config import ASR_SPARK_APP_ID, ASR_SPARK_API_KEY, ASR_SPARK_API_SECRET, IAT_URL

        if not self.current_audio_queue:
            return

        # 修剪过期的音频块
        now_ts = time.monotonic()
        pruned = 0
        temp = []
        while not self.current_audio_queue.empty():
            try:
                item = self.current_audio_queue.get_nowait()
                if item is None:
                    temp.append(None)
                    break
                ts, chunk = item
                if now_ts - ts < 0.4:  # 保留 400ms 内的
                    temp.append((ts, chunk))
                else:
                    pruned += 1
            except asyncio.QueueEmpty:
                break
        for item in temp:
            await self.current_audio_queue.put(item)

        if pruned:
            logger.debug("[Bridge] 修剪过期音频块: %d", pruned)

        # 计算自适应 VAD
        vad_eos = self._compute_adaptive_vad_eos()

        auth_url = assemble_auth_url(IAT_URL, 'GET', ASR_SPARK_API_KEY, ASR_SPARK_API_SECRET)
        async with websockets.connect(auth_url) as ws:
            start_params = {
                "common": {"app_id": ASR_SPARK_APP_ID},
                "business": {
                    "language": "zh_cn", "domain": "iat", "accent": "mandarin",
                    "vad_eos": vad_eos, "ptt": 1, "pd": "0", "nunum": 0, "dwa": "wpgs",
                },
                "data": {"status": 0, "format": "audio/L16;rate=16000", "encoding": "raw", "audio": ""},
            }
            await ws.send(json.dumps(start_params))

            recv_task = asyncio.create_task(self._receive_asr_result(ws))

            # 发送音频
            chunk_count = 0
            timeout_hit = False
            while True:
                try:
                    item = await asyncio.wait_for(self.current_audio_queue.get(), timeout=5.0)
                    if item is None:
                        break
                    _, chunk = item
                    audio_b64 = base64.b64encode(chunk).decode()
                    frame = {"data": {"status": 1, "format": "audio/L16;rate=16000", "encoding": "raw", "audio": audio_b64}}
                    await ws.send(json.dumps(frame))
                    chunk_count += 1
                except asyncio.TimeoutError:
                    timeout_hit = True
                    break

            end_frame = {"data": {"status": 2, "format": "audio/L16;rate=16000", "encoding": "raw", "audio": ""}}
            await ws.send(json.dumps(end_frame))

            result_text = await recv_task

            # 更新 VAD 指标
            has_result = bool(result_text.strip())
            self._record_asr_round_metrics(chunk_count=chunk_count, timeout_hit=timeout_hit, has_result=has_result)

            if result_text:
                await self._send_to_frontend({"type": "asr_result", "content": result_text})
                await self._handle_user_text(result_text, source="asr")
            else:
                self._consecutive_empty += 1

    async def _receive_asr_result(self, ws) -> str:
        """接收 ASR 结果"""
        result_text = ""
        async for message in ws:
            data = json.loads(message)
            if data.get('code', -1) != 0:
                break
            result = data.get('data', {}).get('result', {})
            for ws_item in result.get('ws', []):
                for cw in ws_item.get('cw', []):
                    result_text += cw.get('w', '')
            if data.get('data', {}).get('status') == 2:
                break
        return result_text

    def _compute_adaptive_vad_eos(self) -> int:
        """计算自适应 VAD 超时"""
        vad = self._vad_eos
        if self._consecutive_empty >= 3:
            vad += 180
        if self._empty_rate >= 0.6:
            vad += 120
        if len(self._round_metrics) >= 3:
            avg_chunks = sum(m.get("chunk_count", 0) for m in self._round_metrics[-5:]) / min(5, len(self._round_metrics))
            if avg_chunks >= 26 and self._empty_rate <= 0.35:
                vad -= 120
            elif avg_chunks >= 18 and self._empty_rate <= 0.45:
                vad -= 60
        return max(800, min(1800, vad))

    def _record_asr_round_metrics(self, chunk_count: int, timeout_hit: bool, has_result: bool):
        """记录 ASR 轮次指标"""
        if has_result:
            self._consecutive_empty = 0
        total = len(self._round_metrics) + 1
        empty_count = sum(1 for m in self._round_metrics if not m.get("has_result"))
        if not has_result:
            empty_count += 1
        self._empty_rate = empty_count / total
        self._round_metrics.append({"chunk_count": chunk_count, "timeout_hit": timeout_hit, "has_result": has_result})
        if len(self._round_metrics) > 20:
            self._round_metrics = self._round_metrics[-20:]

    async def _handle_user_text(self, user_text: str, source: str = "text"):
        """核心方法：用户文本 → AvatarAgent → 回复 → Avatar 视频"""
        from app.avatar.agent import AvatarAgent
        from app.memory.short_term import short_term_service
        from app.memory.session import session_service
        from app.chat.service import get_avatar_chat_usecases

        if not self.session_id:
            # 自动创建会话
            session = await session_service.create_chat_session(
                user_id=self.user_id, module="avatar",
            )
            self.session_id = session.id

        # 1. 保存用户消息
        await short_term_service.save_message(
            user_id=self.user_id,
            session_id=self.session_id,
            role="user",
            content=user_text,
            module="avatar",
        )

        # 2. 通过通用 ChatUseCases 复用附件分析与运行时上下文编排
        chat_uc = get_avatar_chat_usecases()
        agent = AvatarAgent()
        full_response = ""
        async for event in chat_uc.stream_chat_events(
            user_id=self.user_id,
            user_message=user_text,
            session_id=self.session_id,
            stream_runner=agent.chat_stream,
            input_source=source,
        ):
            event_type = str(event.get("event", ""))
            payload = event.get("data")

            if event_type == "text_chunk":
                content = str(payload or "")
                full_response += content
                await self._send_to_frontend({"type": "assistant_chunk", "content": content})

            elif event_type == "tool_result":
                await self._send_to_frontend({"type": "tool_result", "data": payload})

            elif event_type == "tool_error":
                await self._send_to_frontend({"type": "tool_error", "data": payload})

            elif event_type == "complete":
                if not full_response and isinstance(payload, dict):
                    full_response = str(payload.get("full_response", "") or "")

        # 完整回复生成后，一次性发送给虚拟人播报
        if full_response.strip() and self._avatar_controller:
            asyncio.create_task(self._avatar_controller.speak(full_response.strip()))

        # 4. 保存助手回复
        if full_response:
            await short_term_service.save_message(
                user_id=self.user_id,
                session_id=self.session_id,
                role="assistant",
                content=full_response,
                module="avatar",
            )

        # 5. 后台管道（记忆提取 + 画像更新）
        asyncio.create_task(self._post_avatar_pipeline(user_text, full_response))

    async def _post_avatar_pipeline(self, user_msg: str, assistant_msg: str):
        """后台：记忆提取 + 画像更新"""
        from app.memory.session import session_service
        from app.memory.helpers import estimate_token_count

        if not self.session_id:
            return

        try:
            # Token 累加
            combined = f"{user_msg}\n{assistant_msg}"
            token_count = estimate_token_count(combined)
            await session_service.accumulate_session_tokens(
                session_id=self.session_id,
                user_id=self.user_id,
                module="avatar",
                content=combined,
            )

            # TODO: 触发记忆提取和画像更新（使用与 TutorAgent 相同的阈值逻辑）
        except Exception as e:
            logger.error("[Bridge] 后台管道失败: %s", e)

    async def _send_to_frontend(self, data: dict):
        """发送消息到前端 WebSocket"""
        if self.frontend_ws:
            try:
                await self.frontend_ws.send_json(data)
            except Exception as e:
                logger.error("[Bridge] 发送前端消息失败: %s", e)

    async def close(self):
        """关闭所有资源"""
        self.is_listening = False
        if self._asr_loop_task and not self._asr_loop_task.done():
            self._asr_loop_task.cancel()
        if self._avatar_controller:
            await self._avatar_controller.close()


class AvatarBridgeManager:
    """管理所有用户的 RealtimeBridge 实例"""

    def __init__(self):
        self._bridges: dict[int, RealtimeBridge] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def get_or_create_bridge(self, user_id: int) -> RealtimeBridge:
        lock = self._get_lock(user_id)
        async with lock:
            if user_id not in self._bridges:
                bridge = RealtimeBridge(user_id=user_id)
                self._bridges[user_id] = bridge
            return self._bridges[user_id]

    async def get_status(self, user_id: int) -> dict:
        bridge = self._bridges.get(user_id)
        if not bridge:
            return {"connected": False, "state": "idle"}
        return {
            "connected": bridge.frontend_ws is not None,
            "state": "idle",
            "session_id": bridge.session_id,
            "is_listening": bridge.is_listening,
        }

    async def get_stream_info(self, user_id: int) -> dict | None:
        bridge = self._bridges.get(user_id)
        if not bridge or not bridge._avatar_controller:
            return None
        return bridge._avatar_controller._last_stream_info

    async def stop(self, user_id: int):
        bridge = self._bridges.get(user_id)
        if bridge and bridge._avatar_controller:
            await bridge._avatar_controller.stop()

    async def cleanup(self, user_id: int):
        bridge = self._bridges.pop(user_id, None)
        if bridge:
            await bridge.close()


# 模块级单例
avatar_bridge_manager = AvatarBridgeManager()
