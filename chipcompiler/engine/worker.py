"""Small process primitives for one-shot native workers."""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from chipcompiler.utility.file import write_text_atomic

_POLL_SECONDS = 1.0
_TERMINATE_TIMEOUT_SECONDS = 5.0


def worker_command(module: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--ecc-worker", module]
    return [sys.executable, "-m", module]


def read_result(result_path: Path) -> dict | None:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def write_result_atomic(result_path: Path, result: dict) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(result_path, json.dumps(result))


def _signal_process_group(process: subprocess.Popen, sig: int) -> None:
    if os.name == "posix" and process.pid:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
    elif process.poll() is None:
        if sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()


def terminate_process_group(process: subprocess.Popen) -> None:
    """Terminate the whole group, including descendants left by an exited leader."""
    _signal_process_group(process, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    if os.name == "posix":
        _signal_process_group(process, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()
    process.wait()


def spawn(
    module: str,
    payload: dict,
    *,
    result_path: Path,
    stdout=None,
    cwd: str | None = None,
) -> subprocess.Popen:
    result_path = result_path.resolve()
    result_path.unlink(missing_ok=True)
    process = subprocess.Popen(
        worker_command(module),
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        start_new_session=(os.name == "posix"),
    )
    try:
        if process.stdin is None:
            raise RuntimeError("worker stdin is unavailable")
        worker_payload = {
            **payload,
            "result_path": str(result_path),
            "parent_pid": os.getpid(),
        }
        with process.stdin:
            process.stdin.write(json.dumps(worker_payload).encode("utf-8"))
    except BaseException:
        terminate_process_group(process)
        raise
    return process


def poll_until_exit(
    process: subprocess.Popen,
    *,
    result_path: Path,
    on_poll: Callable[[dict | None], None] | None = None,
    cancel: Callable[[], None] | None = None,
) -> int:
    while process.poll() is None:
        if cancel is not None:
            cancel()
        if on_poll is not None:
            on_poll(read_result(result_path))
        time.sleep(_POLL_SECONDS)
    if on_poll is not None:
        on_poll(read_result(result_path))
    return process.wait()


def arm_parent_death_signal(parent_pid: int | None = None) -> None:
    if parent_pid is None:
        import multiprocessing

        parent = multiprocessing.parent_process()
        if parent is None or parent.pid is None:
            return
        parent_pid = parent.pid

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def worker_main(handler: Callable[[dict, dict, Callable[[], None]], bool]) -> int:
    payload = json.loads(sys.stdin.read())
    if sys.platform == "linux":
        arm_parent_death_signal(payload["parent_pid"])
    result_path = Path(payload["result_path"])
    result = {
        "attempt_id": payload["attempt_id"],
        "ok": False,
        "done": False,
        "error": None,
        "events": [],
    }

    def flush() -> None:
        write_result_atomic(result_path, result)

    try:
        result["ok"] = handler(payload, result, flush) is True
    except (Exception, SystemExit) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["done"] = True
    flush()
    return 0 if result["ok"] else 1
