import multiprocessing
import os
import sys


def _configure_pyinstaller_runtime() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        os.environ.setdefault("ECC_PYINSTALLER_ROOT", bundle_root)


def main() -> int | None:
    from chipcompiler.cli.main import main as entrypoint

    return entrypoint()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _configure_pyinstaller_runtime()
    raise SystemExit(main())
