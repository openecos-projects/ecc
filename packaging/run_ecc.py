import multiprocessing
import os
import sys


def _configure_pyinstaller_runtime() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        os.environ.setdefault("ECC_PYINSTALLER_ROOT", bundle_root)


def main() -> int | None:
    arguments = sys.argv[1:]
    if arguments[:1] == ["--ecc-worker"]:
        if len(arguments) != 2:
            raise SystemExit("usage: ecc --ecc-worker <module>")
        if arguments[1] == "chipcompiler.engine.step_subprocess":
            from chipcompiler.engine.step_subprocess import main as entrypoint
        elif arguments[1] == "agent.step_worker":
            from agent.step_worker import main as entrypoint
        else:
            raise SystemExit(f"unknown worker: {arguments[1]}")
        return entrypoint()
    from chipcompiler.cli.main import main as entrypoint

    return entrypoint()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _configure_pyinstaller_runtime()
    raise SystemExit(main())
