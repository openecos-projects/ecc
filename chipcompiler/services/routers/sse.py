#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
SSE 路由端点
"""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..sse import event_manager, SSENotification, NotifyType

router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("/stream/{task_id}")
async def event_stream(task_id: str, request: Request):
    """
    SSE 事件流端点
    
    订阅指定任务的事件流，实时接收通知。
    
    Args:
        task_id: 任务 ID
        request: FastAPI 请求对象
        
    Returns:
        StreamingResponse: SSE 事件流
    """
    
    async def generate():
        # 启动心跳任务
        heartbeat_task = asyncio.create_task(heartbeat_loop(task_id))
        
        try:
            async for notification in event_manager.subscribe(task_id):
                # 检查客户端是否断开
                if await request.is_disconnected():
                    break
                
                # 发送 SSE 格式的消息
                yield notification.to_sse_format()
                
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        }
    )


async def heartbeat_loop(task_id: str):
    """
    心跳循环，定期发送心跳保持连接
    
    Args:
        task_id: 任务 ID
    """
    while True:
        await asyncio.sleep(15)  # 每 15 秒发送心跳
        event_manager.publish(task_id, SSENotification(type=NotifyType.HEARTBEAT))


@router.get("/health")
async def sse_health():
    """SSE 服务健康检查"""
    return {"status": "ok", "service": "sse"}
