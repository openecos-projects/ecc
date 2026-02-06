# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec file for ChipCompiler.

This packages ChipCompiler as a backend API server.
The main user interface is provided by the GUI (Tauri app).

Usage:
    # Build onedir mode (default)
    pyinstaller chipcompiler.spec

    # Build onefile mode
    PYINSTALLER_ONEFILE=1 pyinstaller chipcompiler.spec
"""

import os
import sys
from pathlib import Path

# Project root directory
PROJ_ROOT = Path(SPECPATH)

# Build mode: onefile or onedir (default)
ONEFILE_MODE = os.environ.get('PYINSTALLER_ONEFILE', '0') == '1'

# macOS code signing identity (optional)
CODESIGN_IDENTITY = os.environ.get('APPLE_SIGNING_IDENTITY', None)

block_cipher = None

# Collect all data files that need to be included
datas = [
    # ecc config files
    (str(PROJ_ROOT / 'chipcompiler' / 'tools' / 'ecc' / 'configs'), 'chipcompiler/tools/ecc/configs'),
    # Yosys scripts
    (str(PROJ_ROOT / 'chipcompiler' / 'tools' / 'yosys' / 'configs'), 'chipcompiler/tools/yosys/configs'),
    (str(PROJ_ROOT / 'chipcompiler' / 'tools' / 'yosys' / 'scripts'), 'chipcompiler/tools/yosys/scripts'),
    # benchmark module
    (str(PROJ_ROOT / 'benchmark'), 'benchmark'),
]

ecc_bin_dir = PROJ_ROOT / 'chipcompiler' / 'thirdparty' / 'ecc-tools' / 'bin'
ecc_py_files = list(ecc_bin_dir.glob('ecc_py*.so'))
if not ecc_py_files:
    raise FileNotFoundError(
        f"ecc_py module not found in {ecc_bin_dir}. "
        "Please build it first with: ./build.sh"
    )
binaries = [(str(f), 'chipcompiler/thirdparty/ecc-tools/bin') for f in ecc_py_files]

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # Core dependencies
    'numpy',
    'pandas',
    'matplotlib',
    'scipy',
    'pyjson5',
    'yaml',  # PyYAML's module name is 'yaml', not 'pyyaml'
    'tqdm',
    'klayout',
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
    # ChipCompiler modules
    'chipcompiler',
    'chipcompiler.server',
    'chipcompiler.server.main',
    'chipcompiler.server.routers',
    'chipcompiler.server.schemas',
    'chipcompiler.server.services',
    'chipcompiler.data',
    'chipcompiler.engine',
    'chipcompiler.tools',
    'chipcompiler.tools.ecc',
    'chipcompiler.tools.ecc.builder',
    'chipcompiler.tools.ecc.runner',
    'chipcompiler.tools.ecc.module',
    'chipcompiler.thirdparty.ecc-tools.bin.ecc_py',
    'chipcompiler.tools.yosys',
    'chipcompiler.tools.yosys.builder',
    'chipcompiler.tools.yosys.runner',
    'chipcompiler.tools.yosys.utility',
    'benchmark',
    'benchmark.parameters',
    'benchmark.benchmark',
    # Multiprocessing support
    'multiprocessing',
    'multiprocessing.process',
    'multiprocessing.spawn',
    # Additional scipy submodules
    'scipy.special',
    'scipy.linalg',
    'scipy.sparse',
    # Additional matplotlib backends
    'matplotlib.backends.backend_agg',
    # Numpy submodules (numpy 2.x uses _core instead of core)
    'numpy._core._methods',
    'numpy.lib.format',
]

a = Analysis(
    [str(PROJ_ROOT / 'chipcompiler' / 'server' / 'run_server.py')],
    pathex=[str(PROJ_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'test'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONEFILE_MODE:
    # Single file executable
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='chipcompiler',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=CODESIGN_IDENTITY,
        entitlements_file=None,
    )
else:
    # Directory mode (default)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='chipcompiler',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=CODESIGN_IDENTITY,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='chipcompiler',
    )
