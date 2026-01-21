#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from ..schemas import (
    ECCRequest,
    ECCResponse
)
from ..services import ecc_service

ecc_serv = ecc_service()

router = APIRouter(prefix="/api/project", tags=["project"])

@router.post("/create", response_model=ECCResponse)
async def create_project(request: ECCRequest):
    """
    Create a new ECC project.
    """
    return ecc_serv.create_workspace(request)

@router.post("/open", response_model=ECCResponse)
async def open_project(request: ECCRequest):
    """
    Open an existing ECC project.
    """
    return ecc_serv.load_workspace(request)

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}
