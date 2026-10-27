"""Bounded cleanup of descendants adopted through Linux child-subreaper mode."""

import ctypes
import os
import signal
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_PR_SET_CHILD_SUBREAPER = 36
_PROC_TASK = Path("/proc/self/task")


@dataclass(frozen=True)
class Quiescence:
    orphan_exit_codes: tuple[int, ...]
    cleanup_forced: bool
    remaining_pids: tuple[int, ...]

    @property
    def quiescent(self) -> bool:
        return not self.remaining_pids


def enable_subreaper() -> bool:
    """Adopt orphaned descendants so this process can reap them deterministically."""
    if not Path("/proc/self/stat").is_file():
        return False
    try:
        return ctypes.CDLL(None, use_errno=True).prctl(
            _PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0
        ) == 0
    except (OSError, AttributeError):
        return False


def child_pids() -> list[int]:
    pids: set[int] = set()
    for path in _PROC_TASK.glob("*/children"):
        try:
            pids.update(int(item) for item in path.read_text().split())
        except (OSError, ValueError):
            continue
    return sorted(pids)


def reap_available() -> list[int]:
    exit_codes = []
    for pid in child_pids():
        try:
            reaped, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue
        if reaped:
            exit_codes.append(os.waitstatus_to_exitcode(status))
    return exit_codes


def quiesce_descendants(
    timeout_seconds: float = 30.0,
    termination_seconds: float = 5.0,
) -> Quiescence:
    """Wait for adopted descendants, then terminate and reap any stragglers."""
    exit_codes: list[int] = []
    forced = False
    started = time.monotonic()
    graceful_deadline = started + timeout_seconds
    terminate_deadline = graceful_deadline + termination_seconds
    kill_deadline = terminate_deadline + termination_seconds
    terminated = False
    killed = False
    while True:
        exit_codes.extend(reap_available())
        pids = child_pids()
        if not pids:
            return Quiescence(tuple(exit_codes), forced, ())
        now = time.monotonic()
        if not terminated and now >= graceful_deadline:
            forced = True
            terminated = True
            _signal_all(pids, signal.SIGTERM)
        if not killed and now >= terminate_deadline:
            killed = True
            _signal_all(child_pids(), signal.SIGKILL)
        if now >= kill_deadline:
            exit_codes.extend(reap_available())
            return Quiescence(tuple(exit_codes), forced, tuple(child_pids()))
        time.sleep(0.05)


def _signal_all(pids: list[int], signum: int) -> None:
    for pid in pids:
        with suppress(ProcessLookupError):
            os.kill(pid, signum)
