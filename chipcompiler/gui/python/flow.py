#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDA Flow 执行脚本
"""

import json
import sys


def run_flow(route_name: str) -> dict:
    """
    执行 EDA 流程
    
    Args:
        route_name: 当前路由名称
        
    Returns:
        dict: 执行结果
    """
    # 将接收到的参数格式化返回
    result = {
        "status": "success",
        "message": f"收到来自前端的请求，当前路由: {route_name}",
        "data": {
            "route_name": route_name,
            "received_at": "flow.py::run_flow",
            "echo": f"Hello from Python! You are at route: {route_name}"
        }
    }
    
    return result
