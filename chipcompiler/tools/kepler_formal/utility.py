#!/usr/bin/env python
import os
import shutil
from pathlib import Path

from chipcompiler.tools.yosys_lec.utility import lec_result_is_proven, lec_result_status
from chipcompiler.utility import file_digest  # noqa: F401 -- re-exported with the result contract

__all__ = [
    "get_kepler_formal_command",
    "get_kepler_formal_not_found_error",
    "get_kepler_formal_runtime",
    "is_eda_exist",
    "lec_result_is_proven",
    "lec_result_status",
]

_KEPLER_FORMAL_ROOT_ENV = "CHIPCOMPILER_KEPLER_FORMAL_ROOT"
_EXECUTABLE_NAME = "kepler-formal"


def _resolve_kepler_formal_command() -> list[str]:
    """
    Resolve kepler-formal from CHIPCOMPILER_KEPLER_FORMAL_ROOT, then PATH.

    Release archives bundle a root-level ``kepler-formal`` wrapper that points
    LD_LIBRARY_PATH at the bundled naja libraries; prefer it over the raw
    ``bin/kepler-formal`` binary, which needs that path set by the caller.

    Returns:
        list with the executable command, or an empty list if unavailable.
    """
    root = os.environ.get(_KEPLER_FORMAL_ROOT_ENV, "").strip()
    if root:
        root_path = Path(root)
        for candidate in (root_path / _EXECUTABLE_NAME, root_path / "bin" / _EXECUTABLE_NAME):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return [str(candidate)]

    if shutil.which(_EXECUTABLE_NAME):
        return [_EXECUTABLE_NAME]

    return []


def get_kepler_formal_not_found_error() -> str:
    """
    Build a clear error message when kepler-formal cannot be resolved.
    """
    root = os.environ.get(_KEPLER_FORMAL_ROOT_ENV, "").strip()
    if root:
        return (
            "kepler-formal executable not found. "
            f"Checked CHIPCOMPILER_KEPLER_FORMAL_ROOT='{root}' (expected the "
            f"root-level wrapper or 'bin/{_EXECUTABLE_NAME}') and system PATH. "
            "Please install kepler-formal or fix CHIPCOMPILER_KEPLER_FORMAL_ROOT."
        )

    return (
        "kepler-formal executable not found in system PATH, and "
        f"{_KEPLER_FORMAL_ROOT_ENV} is not set. Please install kepler-formal "
        f"or set {_KEPLER_FORMAL_ROOT_ENV} to the kepler-formal release root."
    )


def get_kepler_formal_command() -> list[str]:
    """
    Get the kepler-formal command to use.

    Side-effect free and never mutates os.environ.
    """
    return _resolve_kepler_formal_command()


def _sanitize_loader_env(env: dict[str, str]) -> dict[str, str]:
    """Drop loader vars inherited from the ECC process.

    The sidecar environment can prepend torch/ecc_tools library directories to
    LD_LIBRARY_PATH; kepler-formal bundles its own TBB and naja libraries and
    its wrapper rebuilds LD_LIBRARY_PATH from scratch.
    """
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def get_kepler_formal_runtime() -> tuple[list[str], dict[str, str]]:
    """
    Get kepler-formal command and subprocess environment.

    Environment variables are only prepared for the subprocess and never
    written to global os.environ.
    """
    command = _resolve_kepler_formal_command()
    env = _sanitize_loader_env(os.environ.copy())
    return command, env


def is_eda_exist() -> bool:
    """
    Check if kepler-formal is available via CHIPCOMPILER_KEPLER_FORMAL_ROOT or PATH.
    """
    if get_kepler_formal_command():
        return True

    raise RuntimeError(get_kepler_formal_not_found_error())
