from __future__ import annotations

import multiprocessing
import os
import sys

from chipcompiler.cli.main import main


def _configure_pyinstaller_runtime() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        os.environ.setdefault("ECC_PYINSTALLER_ROOT", bundle_root)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _configure_pyinstaller_runtime()
    main()
