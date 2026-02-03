#!/usr/bin/env python

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import workspace_router

# Create FastAPI application
app = FastAPI(
    title="ChipCompiler API", description="Backend API for ChipCompiler EDA tool", version="0.1.0"
)

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",  # Tauri dev server
        "http://127.0.0.1:1420",
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        "tauri://localhost",  # Tauri production (v1 style)
        "https://tauri.localhost",  # Tauri v2 production
        "http://tauri.localhost",  # Tauri v2 production (http)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(workspace_router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"name": "ChipCompiler API", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    """Global health check"""
    return {"status": "ok"}
