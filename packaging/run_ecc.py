import multiprocessing
import os
import sys
from pathlib import Path


def _configure_pyinstaller_runtime() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        os.environ.setdefault("ECC_PYINSTALLER_ROOT", bundle_root)


def main() -> int | None:
    if Path(sys.argv[0]).stem == "ecc-agent-rpc":
        from agent.rpc_server import main as entrypoint
    else:
        from chipcompiler.cli.main import main as entrypoint
    return entrypoint()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _configure_pyinstaller_runtime()
    raise SystemExit(main())
