#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
SSE 通知模型定义
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional
import time


class NotifyType(str, Enum):
    """SSE 通知类型"""
    DATA_READY = "data_ready"       # 数据已就绪，可调用 get_info
    STEP_START = "step_start"       # step 开始执行
    STEP_COMPLETE = "step_complete" # step 执行完成
    TASK_COMPLETE = "task_complete" # 整个任务完成
    ERROR = "error"                 # 发生错误
    HEARTBEAT = "heartbeat"         # 心跳保活
    MESSAGE = "message"             # 通用消息


class SSENotification(BaseModel):
    """SSE 通知数据模型"""
    type: NotifyType
    step: Optional[str] = None         # 相关的 step 名称
    id: Optional[str] = None           # get_info 的 id 参数
    message: Optional[str] = None      # 可选的消息
    timestamp: float = 0.0             # 时间戳
    
    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] == 0.0:
            data["timestamp"] = time.time()
        super().__init__(**data)
    
    def to_sse_format(self) -> str:
        """转换为 SSE 格式字符串"""
        lines = [
            f"event: {self.type.value}",
            f"data: {self.model_dump_json()}",
            "",  # SSE 消息以空行结束
        ]
        return "\n".join(lines) + "\n"
