# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ChipCompiler API Server.

This spec file configures the build of the FastAPI server as a standalone executable.
The executable will be used by the Tauri application in production mode.

Usage:
    pyinstaller api-server.spec
"""

import sys
import os
from pathlib import Path

# Get the project root directory
spec_dir = Path(SPECPATH)
project_root = spec_dir.parent.parent  # chipcompiler/server -> project_root

# Add project root to path for analysis
sys.path.insert(0, str(project_root))

block_cipher = None

# Collect all chipcompiler modules
hidden_imports = [
    'chipcompiler',
    'chipcompiler.server',
    'chipcompiler.server.main',
    'chipcompiler.server.routers',
    'chipcompiler.server.routers.ecc',
    'chipcompiler.server.routers.sse',
    'chipcompiler.server.schemas',
    'chipcompiler.server.schemas.ecc',
    'chipcompiler.server.schemas.info',
    'chipcompiler.server.services',
    'chipcompiler.server.services.ecc',
    'chipcompiler.server.services.info',
    'chipcompiler.server.sse',
    'chipcompiler.server.sse.manager',
    'chipcompiler.server.sse.models',
    'chipcompiler.server.sse.notify_service',
    'chipcompiler.data',
    'chipcompiler.data.workspace',
    'chipcompiler.data.parameter',
    'chipcompiler.data.step',
    'chipcompiler.utility',
    'chipcompiler.utility.json',
    'chipcompiler.utility.log',
    'chipcompiler.utility.file',
    'chipcompiler.utility.filelist',
    'chipcompiler.utility.util',
    # FastAPI and dependencies
    'fastapi',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'starlette',
    'pydantic',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
]

a = Analysis(
    ['run_server.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'klayout',
        'tkinter',
        'PyQt5',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='api-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for logging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
