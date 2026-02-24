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
from PyInstaller.utils.hooks import collect_all

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
]

# Collect klayout package resources (including db_plugins format readers).
klayout_datas, klayout_binaries, klayout_hiddenimports = collect_all('klayout')
datas.extend(klayout_datas)

ecc_bin_dir = PROJ_ROOT / 'chipcompiler' / 'tools' / 'ecc' / 'bin'
all_ecc_py_files = sorted(ecc_bin_dir.glob('ecc_py*.so'))

if not all_ecc_py_files:
    raise FileNotFoundError(
        f"ecc_py module not found in {ecc_bin_dir}. "
        "Build and install runtime first, for example: "
        "bazel run //chipcompiler/thirdparty:install_ecc_runtime"
    )

py_tag_cpython = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
py_tag_cp = f"cp{sys.version_info.major}{sys.version_info.minor}"

def _is_abi_compatible(path: Path) -> bool:
    name = path.name
    return (
        name == 'ecc_py.so'
        or py_tag_cpython in name
        or py_tag_cp in name
    )

ecc_py_files = [f for f in all_ecc_py_files if _is_abi_compatible(f)]
if not ecc_py_files:
    raise RuntimeError(
        "Found ecc_py shared libraries, but none are compatible with this Python ABI "
        f"({py_tag_cpython}/{py_tag_cp}). Found: "
        + ", ".join(str(p.name) for p in all_ecc_py_files)
    )

# Runtime imports ecc from chipcompiler.tools.ecc.bin.
# Always place the extension under this package in the bundle.
binaries = [(str(f), 'chipcompiler/tools/ecc/bin') for f in ecc_py_files]
# Explicit runtime dependency: bundle all ECC runtime shared libs.
if sys.platform.startswith("linux"):
    ecc_lib_dir = ecc_bin_dir / "lib"
    if not ecc_lib_dir.is_dir():
        raise FileNotFoundError(
            f"ECC runtime lib directory not found: {ecc_lib_dir}. "
            "Run: bazel run //chipcompiler/thirdparty:install_ecc_runtime"
        )
    ecc_runtime_libs = sorted(p for p in ecc_lib_dir.glob("*.so*") if p.is_file())
    if not ecc_runtime_libs:
        raise FileNotFoundError(
            f"No runtime shared libraries found in {ecc_lib_dir}. "
            "Run: bazel run //chipcompiler/thirdparty:install_ecc_runtime"
        )
    binaries.extend((str(p), 'chipcompiler/tools/ecc/bin/lib') for p in ecc_runtime_libs)

# Add system libraries
binaries.extend([
    ('/lib/x86_64-linux-gnu/libgomp.so.1', 'lib'),
    ('/lib/x86_64-linux-gnu/libtbb.so.12', 'lib'),
])
binaries.extend(klayout_binaries)

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
    'chipcompiler.utility.log',
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
    'chipcompiler.tools.ecc.bin.ecc_py',
    'chipcompiler.tools.yosys',
    'chipcompiler.tools.yosys.builder',
    'chipcompiler.tools.yosys.runner',
    'chipcompiler.tools.yosys.utility',
    'chipcompiler.tools.klayout_tool',
    'chipcompiler.tools.klayout_tool.builder',
    'chipcompiler.tools.klayout_tool.runner',
    'chipcompiler.tools.klayout_tool.module',
    'chipcompiler.tools.klayout_tool.utility',
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
hiddenimports.extend(klayout_hiddenimports)

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
