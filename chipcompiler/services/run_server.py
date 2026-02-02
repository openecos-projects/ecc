#!/usr/bin/env python

"""
Standalone script to run the FastAPI server.
This script is intended to be spawned by Tauri at application startup.
"""

import os
import sys

# Add project root to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run ChipCompiler API server")
    parser.add_argument(
        "--host", 
        default="127.0.0.1", 
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8765, 
        help="Port to bind to (default: 8765)"
    )
    parser.add_argument(
        "--reload", 
        action="store_true", 
        help="Enable auto-reload for development"
    )
    
    args = parser.parse_args()
    
    print(f"Starting ChipCompiler API server on {args.host}:{args.port}")
    
    uvicorn.run(
        "chipcompiler.services.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
