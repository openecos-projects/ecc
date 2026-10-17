"""Interactive KLayout viewer helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from chipcompiler.utility.path import path_text


class KlayoutUnavailableError(OSError):
    """Raised when the interactive KLayout executable cannot be located."""


def _klayout_executable() -> str:
    configured = os.environ.get("KLAYOUT_BIN")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise KlayoutUnavailableError(f"KLAYOUT_BIN is not an executable file: {candidate}")

    executable = shutil.which("klayout")
    if executable:
        return executable
    raise KlayoutUnavailableError("KLayout GUI executable was not found in KLAYOUT_BIN or PATH")


def view_gds(gds_file: str | Path) -> None:
    """Open a GDS file in KLayout and wait until its GUI window closes."""
    path = Path(gds_file)
    if not path.is_file():
        raise OSError(f"GDS file does not exist: {path}")

    executable = _klayout_executable()
    result = subprocess.run(
        [executable, path_text(path)],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"KLayout exited with status {result.returncode}")
