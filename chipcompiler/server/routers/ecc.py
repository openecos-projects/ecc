#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from ..schemas import (
    ECCRequest,
    ECCResponse
)
from ..services import ecc_service

ecc_serv = ecc_service()

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

@router.post("/create_workspace", response_model=ECCResponse)
async def create_workspace(request: ECCRequest):
    """
    Create a new ECC project.
    """
    return ecc_serv.create_workspace(request)

@router.post("/load_workspace", response_model=ECCResponse)
async def load_workspace(request: ECCRequest):
    """
    Open an existing ECC project.
    """
    return ecc_serv.load_workspace(request)

@router.post("/delete_workspace", response_model=ECCResponse)
async def delete_workspace(request: ECCRequest):
    """
    Delete an existing ECC project.
    """
    return ecc_serv.delete_workspace(request)

@router.post("/rtl2gds", response_model=ECCResponse)
async def rtl2gds(request: ECCRequest):
    """
    run rtl2gds flow for current workspace.
    """
    return ecc_serv.rtl2gds(request)

@router.post("/run_step", response_model=ECCResponse)
async def run_step(request: ECCRequest):
    """
    run step for current workspace.
    """
    return ecc_serv.run_step(request)

@router.post("/get_info", response_model=ECCResponse)
async def get_info(request: ECCRequest):
    """
    get information by step and id.
    """
    return ecc_serv.get_info(request)

@router.post("/get_home_page", response_model=ECCResponse)
async def get_home_page(request: ECCRequest):
    """
    get home page information.
    """
    return ecc_serv.get_home_page(request)