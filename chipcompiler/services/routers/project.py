#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from ..schemas import (
    OpenProjectRequest,
    CreateProjectRequest,
    ProjectInfo,
    ProjectResponse
)
from ..services import ProjectService

router = APIRouter(prefix="/api/project", tags=["project"])


@router.post("/open", response_model=ProjectResponse)
async def open_project(request: OpenProjectRequest):
    """
    Open an existing ECC project.
    
    - **path**: Full path to the project directory
    """
    success, message, project_info = ProjectService.open_project(request.path)
    
    if not success:
        return ProjectResponse(
            status="error",
            message=message,
            project=None
        )
    
    return ProjectResponse(
        status="success",
        message=message,
        project=ProjectInfo(**project_info) if project_info else None
    )


@router.post("/create", response_model=ProjectResponse)
async def create_project(request: CreateProjectRequest):
    """
    Create a new ECC project.
    
    - **path**: Parent directory where the project will be created
    - **name**: Name of the new project (defaults to "New_Chip_Design")
    """
    success, message, project_info = ProjectService.create_project(
        request.path, 
        request.name
    )
    
    if not success:
        return ProjectResponse(
            status="error",
            message=message,
            project=None
        )
    
    return ProjectResponse(
        status="success",
        message=message,
        project=ProjectInfo(**project_info) if project_info else None
    )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}
