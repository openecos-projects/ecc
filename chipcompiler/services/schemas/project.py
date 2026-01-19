#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from pydantic import BaseModel
from typing import Optional, Dict, Any


class OpenProjectRequest(BaseModel):
    """Request model for opening an existing project"""
    path: str


class CreateProjectRequest(BaseModel):
    """Request model for creating a new project"""
    path: str
    name: str = "New_Chip_Design"


class ProjectInfo(BaseModel):
    """Project information model"""
    name: str
    path: str
    flow: Optional[Dict[str, Any]] = None


class ProjectResponse(BaseModel):
    """Standard response model for project operations"""
    status: str  # "success" or "error"
    message: Optional[str] = None
    project: Optional[ProjectInfo] = None
