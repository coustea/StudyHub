# -*- coding: utf-8 -*-
"""
AvatarAgent schemas — 请求/响应数据模型
"""

from pydantic import BaseModel


class StopRequest(BaseModel):
    pass  # user_id 从 JWT 获取


class SwitchSessionRequest(BaseModel):
    session_id: str
