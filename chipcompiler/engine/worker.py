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


def arm_parent_death_signal(
    parent_pid: int | None = None, *, death_signal: int = signal.SIGKILL
) -> None:
    if parent_pid is None:
        import multiprocessing

        parent = multiprocessing.parent_process()
        if parent is None or parent.pid is None:
            return
        parent_pid = parent.pid

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, death_signal, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), death_signal)


def _parent_death_watchdog(worker_pid: int, channel) -> None:
    def kill_worker_group(_signum=None, _frame=None):
        with suppress(ProcessLookupError):
            os.killpg(worker_pid, signal.SIGKILL)
        os._exit(0)

    signal.signal(signal.SIGTERM, kill_worker_group)
    arm_parent_death_signal(worker_pid, death_signal=signal.SIGTERM)
    with suppress(BrokenPipeError, EOFError):
        channel.send(None)
    try:
        channel.recv()
    except EOFError:
        kill_worker_group()
    channel.close()


def _start_parent_death_watchdog():
    import multiprocessing

    parent_channel, child_channel = multiprocessing.Pipe(duplex=True)
    process = multiprocessing.get_context("spawn").Process(
        target=_parent_death_watchdog, args=(os.getpid(), child_channel), daemon=True
    )
    try:
        process.start()
    except BaseException:
        parent_channel.close()
        child_channel.close()
        raise
    child_channel.close()
    try:
        if not parent_channel.poll(5.0):
            process.kill()
            process.join()
            raise RuntimeError("worker watchdog did not arm within 5 seconds")
        parent_channel.recv()
    except BaseException:
        parent_channel.close()
        raise
    return process, parent_channel


def _stop_parent_death_watchdog(watchdog) -> None:
    process, channel = watchdog
    with suppress(BrokenPipeError, EOFError):
        channel.send(None)
    channel.close()
    process.join(timeout=5.0)
    if process.is_alive():
        process.terminate()
        process.join()
    process.close()


def worker_main(handler: Callable[[dict, dict, Callable[[], None]], bool]) -> int:
    payload = json.loads(sys.stdin.read())
    watchdog = None
    if sys.platform == "linux":
        arm_parent_death_signal(payload["parent_pid"])
        watchdog = _start_parent_death_watchdog()
    try:
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
    finally:
        if watchdog is not None:
            _stop_parent_death_watchdog(watchdog)
