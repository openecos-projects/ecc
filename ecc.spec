# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec file for ChipCompiler.

This packages ChipCompiler as a backend API server (onefile mode).
The main user interface is provided by the GUI (Tauri app).

Usage:
    bazel build //:api_server_bundle
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# Project root directory
PROJ_ROOT = Path(SPECPATH)

# macOS code signing identity (optional)
CODESIGN_IDENTITY = os.environ.get("APPLE_SIGNING_IDENTITY")

# --- Data files ---
datas = [
    (
        str(PROJ_ROOT / "chipcompiler" / "tools" / "ecc" / "configs"),
        "chipcompiler/tools/ecc/configs",
    ),
    (
        str(PROJ_ROOT / "chipcompiler" / "tools" / "yosys" / "configs"),
        "chipcompiler/tools/yosys/configs",
    ),
    (
        str(PROJ_ROOT / "chipcompiler" / "tools" / "yosys" / "scripts"),
        "chipcompiler/tools/yosys/scripts",
    ),
]

# Collect klayout package resources (including db_plugins format readers).
klayout_datas, klayout_binaries, klayout_hiddenimports = collect_all("klayout")
datas.extend(klayout_datas)

# --- ECC native binaries ---
ecc_bin_dir = PROJ_ROOT / "chipcompiler" / "tools" / "ecc" / "bin"
all_ecc_py_files = sorted(ecc_bin_dir.glob("ecc_py*.so"))

if not all_ecc_py_files:
    raise FileNotFoundError(
        f"ecc_py module not found in {ecc_bin_dir}. "
        "Build and install runtime first: "
        "bazel build //chipcompiler/thirdparty:ecc_bundle"
    )

py_tag_cpython = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
py_tag_cp = f"cp{sys.version_info.major}{sys.version_info.minor}"


def _is_abi_compatible(path: Path) -> bool:
    name = path.name
    return name == "ecc_py.so" or py_tag_cpython in name or py_tag_cp in name


ecc_py_files = [f for f in all_ecc_py_files if _is_abi_compatible(f)]
if not ecc_py_files:
    raise RuntimeError(
        "Found ecc_py shared libraries, but none are compatible with this Python ABI "
        f"({py_tag_cpython}/{py_tag_cp}). Found: "
        + ", ".join(str(p.name) for p in all_ecc_py_files)
    )

binaries = [(str(f), "chipcompiler/tools/ecc/bin") for f in ecc_py_files]

# Bundle ECC runtime shared libs (RPATH expects $ORIGIN/lib).
if sys.platform.startswith("linux"):
    ecc_lib_dir = ecc_bin_dir / "lib"
    ecc_runtime_libs = sorted(p for p in ecc_lib_dir.glob("*.so*") if p.is_file())
    if not ecc_runtime_libs:
        raise FileNotFoundError(
            f"No ECC runtime shared libraries found in {ecc_lib_dir}. "
            "Run: bazel build //chipcompiler/thirdparty:ecc_bundle"
        )
    binaries.extend((str(p), "chipcompiler/tools/ecc/bin/lib") for p in ecc_runtime_libs)

binaries.extend(
    [
        ("/lib/x86_64-linux-gnu/libgomp.so.1", "lib"),
        ("/lib/x86_64-linux-gnu/libtbb.so.12", "lib"),
    ]
)
binaries.extend(klayout_binaries)

# --- Hidden imports ---
hiddenimports = [
    # Core dependencies
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "pyjson5",
    "yaml",
    "tqdm",
    "klayout",
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "anyio",
    # uvicorn internals
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "anyio._backends",
    "anyio._backends._asyncio",
    # ChipCompiler modules
    "chipcompiler",
    "chipcompiler.server",
    "chipcompiler.server.main",
    "chipcompiler.utility.log",
    "chipcompiler.server.routers",
    "chipcompiler.server.schemas",
    "chipcompiler.server.services",
    "chipcompiler.data",
    "chipcompiler.engine",
    "chipcompiler.tools",
    "chipcompiler.tools.ecc",
    "chipcompiler.tools.ecc.builder",
    "chipcompiler.tools.ecc.runner",
    "chipcompiler.tools.ecc.module",
    "chipcompiler.tools.ecc.bin.ecc_py",
    "chipcompiler.tools.yosys",
    "chipcompiler.tools.yosys.builder",
    "chipcompiler.tools.yosys.runner",
    "chipcompiler.tools.yosys.utility",
    "chipcompiler.tools.klayout_tool",
    "chipcompiler.tools.klayout_tool.builder",
    "chipcompiler.tools.klayout_tool.runner",
    "chipcompiler.tools.klayout_tool.module",
    "chipcompiler.tools.klayout_tool.utility",
    # Multiprocessing support
    "multiprocessing",
    "multiprocessing.process",
    "multiprocessing.spawn",
    # Submodules PyInstaller misses
    "scipy.special",
    "scipy.linalg",
    "scipy.sparse",
    "matplotlib.backends.backend_agg",
    "numpy._core._methods",
    "numpy.lib.format",
]
hiddenimports.extend(klayout_hiddenimports)

# --- Analysis & packaging ---
a = Analysis(
    [str(PROJ_ROOT / "chipcompiler" / "server" / "run_server.py")],
    pathex=[str(PROJ_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="chipcompiler",
    strip=False,
    upx=True,
    console=True,
    codesign_identity=CODESIGN_IDENTITY,
)
