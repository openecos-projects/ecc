"""
PyInstaller spec for the ECC CLI.

Build:
    uv run pyinstaller ecc.spec --clean --noconfirm
"""
# ruff: noqa: F821

import os
import sys
import warnings
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

from chipcompiler.pyinstaller_utils import (
    collect_package_extension_binaries,
    filter_collected_payloads,
    filter_hiddenimports,
)

ECC_DIR = Path(SPECPATH)
HOOKS_DIR = ECC_DIR / "hooks"
CODESIGN_IDENTITY = os.environ.get("APPLE_SIGNING_IDENTITY")
BUNDLE_MODE = os.environ.get("ECOS_PYINSTALLER_MODE", "onedir").strip().lower()

if BUNDLE_MODE not in {"onedir", "onefile"}:
    raise SystemExit(f"Unsupported ECOS_PYINSTALLER_MODE={BUNDLE_MODE!r}; use onedir or onefile.")

REQUIRED_DISTRIBUTION_METADATA = (
    "ecc",
    "ecc-dreamplace",
    "ecc-tools-bin",
)

ECC_PACKAGE_RESOURCES = (
    "chipcompiler/tools/ecc/configs",
    "chipcompiler/tools/yosys/configs",
    "chipcompiler/tools/yosys/scripts",
    "chipcompiler/tools/ecc_dreamplace/configs/dreamplace_ecc.json",
)

DREAMPLACE_THIRDPARTY_FILES = (
    "thirdparty/flute/lut.ICCAD2015/POWV9.dat",
    "thirdparty/flute/lut.ICCAD2015/POST9.dat",
    "thirdparty/NCTUgr.ICCAD2012/NCTUgr",
    "thirdparty/NCTUgr.ICCAD2012/PORT9.dat",
    "thirdparty/NCTUgr.ICCAD2012/POST9.dat",
    "thirdparty/NCTUgr.ICCAD2012/POWV9.dat",
    "thirdparty/NCTUgr.ICCAD2012/DAC12.set",
    "thirdparty/NCTUgr.ICCAD2012/ICCAD12.set",
)

DOC_GUIDES = (
    "chipcompiler/docs/ecc-config-ref.en.md",
    "chipcompiler/docs/ecc-config-ref.cn.md",
    "chipcompiler/docs/ecc-user-guide.en.md",
    "chipcompiler/docs/ecc-user-guide.cn.md",
    "chipcompiler/docs/ecc-tutorial.en.md",
    "chipcompiler/docs/ecc-tutorial.cn.md",
)

LINUX_RUNTIME_LIBS = (
    "/lib/x86_64-linux-gnu/libgomp.so.1",
    "/lib/x86_64-linux-gnu/libtbb.so.12",
    "/lib/x86_64-linux-gnu/libcairo.so.2",
    "/lib/x86_64-linux-gnu/libX11.so.6",
    "/lib/x86_64-linux-gnu/libxcb.so.1",
    "/lib/x86_64-linux-gnu/libxcb-render.so.0",
    "/lib/x86_64-linux-gnu/libxcb-shm.so.0",
    "/lib/x86_64-linux-gnu/libpng16.so.16",
    "/lib/x86_64-linux-gnu/libfreetype.so.6",
)

HIDDENIMPORTS = [
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "torch",
    "pyjson5",
    "yaml",
    "tqdm",
    "klayout",
    "click",
    "typer",
    "chipcompiler",
    "chipcompiler.cli",
    "chipcompiler.data",
    "chipcompiler.engine",
    "chipcompiler.tools",
    "chipcompiler.tools.ecc",
    "chipcompiler.tools.ecc.builder",
    "chipcompiler.tools.ecc.runner",
    "chipcompiler.tools.ecc.module",
    "chipcompiler.tools.ecc.bin.ecc_py",
    "chipcompiler.tools.ecc_dreamplace",
    "chipcompiler.tools.ecc_dreamplace.builder",
    "chipcompiler.tools.ecc_dreamplace.runner",
    "chipcompiler.tools.ecc_dreamplace.module",
    "chipcompiler.tools.yosys",
    "chipcompiler.tools.yosys.builder",
    "chipcompiler.tools.yosys.runner",
    "chipcompiler.tools.yosys.utility",
    "chipcompiler.tools.klayout_tool",
    "chipcompiler.tools.klayout_tool.builder",
    "chipcompiler.tools.klayout_tool.image",
    "chipcompiler.tools.klayout_tool.runner",
    "chipcompiler.tools.klayout_tool.module",
    "chipcompiler.tools.klayout_tool.utility",
    "multiprocessing",
    "multiprocessing.process",
    "multiprocessing.spawn",
    "scipy.special",
    "scipy.linalg",
    "scipy.sparse",
    "matplotlib.backends.backend_agg",
    "numpy.core",
    "numpy.core.multiarray",
    "numpy.core._multiarray_umath",
    "numpy.core.umath",
    "numpy._core._methods",
    "numpy._core.multiarray",
    "numpy.lib.format",
]

EXCLUDES = [
    "tkinter",
    "test",
    "setuptools",
    "_distutils_hack",
    "mypy",
    "pip",
    "pkg_resources",
]


def collect_required_metadata():
    metadata = []
    for dist_name in REQUIRED_DISTRIBUTION_METADATA:
        try:
            metadata.extend(copy_metadata(dist_name))
        except Exception as exc:
            raise SystemExit(
                f"Missing required distribution metadata for '{dist_name}'. "
                "Ensure the locked development environment is installed before packaging."
            ) from exc
    return metadata


def collect_ecc_resources():
    datas = []
    for resource in ECC_PACKAGE_RESOURCES:
        package_name, include_path = resource.split("/", 1)
        collected = collect_data_files(package_name, includes=[include_path])
        if collected:
            datas.extend(collected)
        else:
            warnings.warn(
                f"Required ECC runtime resource was not collected: {resource}",
                stacklevel=2,
            )
    return datas


def collect_jsonrpcserver_resources():
    return collect_data_files("jsonrpcserver")


def collect_dreamplace_thirdparty_files():
    datas = []
    thirdparty_root = ECC_DIR / "chipcompiler" / "thirdparty" / "ecc-dreamplace"
    for relpath in DREAMPLACE_THIRDPARTY_FILES:
        src = thirdparty_root / relpath
        if src.exists():
            datas.append((str(src), str(Path(relpath).parent)))
        else:
            warnings.warn(
                f"DreamPlace thirdparty file not found and will not be bundled: {src}",
                stacklevel=2,
            )
    return datas


def collect_doc_guides():
    datas = []
    for relpath in DOC_GUIDES:
        src = ECC_DIR / relpath
        if src.is_file():
            datas.append((str(src), "docs"))
        else:
            warnings.warn(
                f"Required ECC runtime resource was not collected: {relpath}",
                stacklevel=2,
            )
    return datas


def collect_platform_runtime_libs():
    if sys.platform.startswith("linux"):
        binaries = []
        for so_path in LINUX_RUNTIME_LIBS:
            if Path(so_path).exists():
                binaries.append((so_path, "."))
            else:
                warnings.warn(
                    f"Optional runtime library not found and will not be bundled: {so_path}",
                    stacklevel=2,
                )
        return binaries
    elif sys.platform == "darwin":  # noqa: SIM114 - keep platform branches explicit.
        return []
    elif sys.platform == "win32":
        return []
    return []


def collect_ecc_tools_extension_binaries():
    module_spec = find_spec("ecc_tools_bin")
    if module_spec is None or module_spec.submodule_search_locations is None:
        return []

    return collect_package_extension_binaries(
        module_spec.submodule_search_locations,
        "ecc_py*.so",
        "ecc_tools_bin",
    )


def filter_host_fontconfig(binaries):
    # PyInstaller pulls libfontconfig in as a DT_NEEDED dependency of the
    # bundled libcairo. Do not ship it: a bundled library parses the host's
    # /etc/fonts/conf.d, and version skew against those host configs spams
    # Fontconfig warnings (and breaks the host fc-list binary with symbol
    # errors when the bundle lib dir is on its library search path). The
    # host libfontconfig always matches the host fontconfig data. Applied
    # to the Analysis output, because input-list filtering cannot stop the
    # dependency walk from re-collecting it.
    #
    # Consequence (verified host prerequisite): the bundle keeps libcairo
    # (PyInstaller dependency) and DreamPlace's draw_place_cpp loads
    # fontconfig through it, so a supported host must provide
    # libfontconfig.so.1 itself (any glibc-based distro with fontconfig
    # installed qualifies; a bare container without fontconfig will fail
    # placement with a loader error).
    return [
        entry
        for entry in binaries
        if not any(Path(part).name.startswith("libfontconfig.so") for part in entry[:2])
    ]


def rich_unicode_data_hiddenimports():
    # rich imports its per-Unicode-version cell-width tables dynamically
    # (rich._unicode_data.unicode<N>-<N>-<N>), so PyInstaller's static
    # analysis cannot see them; render-only CJK output needs them at runtime.
    module_spec = find_spec("rich")
    if module_spec is None or module_spec.submodule_search_locations is None:
        return []

    names = []
    for package_root in module_spec.submodule_search_locations:
        data_dir = Path(package_root) / "_unicode_data"
        if data_dir.is_dir():
            names.extend(
                f"rich._unicode_data.{path.stem}" for path in sorted(data_dir.glob("unicode*.py"))
            )
    return names


ecc_datas, ecc_binaries, ecc_hiddenimports = collect_all("chipcompiler")
ecc_tools_datas, ecc_tools_binaries, ecc_tools_hiddenimports = collect_all("ecc_tools_bin")
klayout_datas, klayout_binaries, klayout_hiddenimports = collect_all("klayout")
dreamplace_datas, dreamplace_binaries, dreamplace_hiddenimports = collect_all("dreamplace")
torch_datas, torch_binaries, torch_hiddenimports = collect_all("torch")

datas = []
datas.extend(ecc_datas)
datas.extend(ecc_tools_datas)
datas.extend(klayout_datas)
datas.extend(dreamplace_datas)
datas.extend(torch_datas)
datas.extend(collect_required_metadata())
datas.extend(collect_ecc_resources())
datas.extend(collect_jsonrpcserver_resources())
datas.extend(collect_dreamplace_thirdparty_files())
datas.extend(collect_doc_guides())

binaries = []
binaries.extend(ecc_binaries)
binaries.extend(ecc_tools_binaries)
binaries.extend(collect_ecc_tools_extension_binaries())
binaries.extend(klayout_binaries)
binaries.extend(dreamplace_binaries)
binaries.extend(torch_binaries)
binaries.extend(collect_platform_runtime_libs())
binaries = filter_collected_payloads(binaries)

hiddenimports = []
hiddenimports.extend(HIDDENIMPORTS)
hiddenimports.extend(rich_unicode_data_hiddenimports())
hiddenimports.extend(ecc_hiddenimports)
hiddenimports.extend(ecc_tools_hiddenimports)
hiddenimports.extend(klayout_hiddenimports)
hiddenimports.extend(dreamplace_hiddenimports)
hiddenimports.extend(torch_hiddenimports)
hiddenimports = filter_hiddenimports(hiddenimports)

datas = filter_collected_payloads(datas)

a = Analysis(
    [str(ECC_DIR / "packaging" / "run_ecc.py")],
    pathex=[str(ECC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(HOOKS_DIR)],
    excludes=EXCLUDES,
    noarchive=False,
)

a.binaries = filter_host_fontconfig(a.binaries)

pyz = PYZ(a.pure, a.zipped_data)

if BUNDLE_MODE == "onedir":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ecc",
        strip=False,
        upx=False,
        console=True,
        codesign_identity=CODESIGN_IDENTITY,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name="ecc",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="ecc",
        strip=False,
        upx=True,
        console=True,
        codesign_identity=CODESIGN_IDENTITY,
    )
