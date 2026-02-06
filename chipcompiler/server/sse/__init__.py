#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from .models import to_sse_format
from .manager import EventManager, event_manager
from .notify_service import NotifyService

global _notify_service
_notify_service = NotifyService()

def server_notify():
    global _notify_service
    return _notify_service

__all__ = [
    "to_sse_format",
    "EventManager",
    "event_manager",
    "NotifyService",
    "server_notify"
]
