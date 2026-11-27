"""Observe opt-in step log appends without redirecting or slowing tool stdout.

Times describe when flushed bytes were observed, not when the tool emitted them.
The initial offset excludes previous runs because ECC normally appends step logs.
"""

import logging
import sys
import threading
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path

from chipcompiler.tools.replay_storage import atomic_json, within

logger = logging.getLogger(__name__)
MAX_BYTES = 64 * 1024 * 1024
POLL_SECONDS = 0.1


@contextmanager
def rewriting_log(path):
    """Synchronize an intentional truncate with this worker's log reader."""
    capture = active_log.get()
    if capture is None or Path(path).absolute() != capture.source:
        yield
        return
    with capture.lock:
        yield
        capture.offset = 0
        capture.identity = None


def open_step_log(path: str | Path, *, encoding: str | None = None):
    with rewriting_log(path):
        return open(path, "w", encoding=encoding)


class LogCapture:
    def __init__(self, source: Path, directory: Path, started_ns: int):
        self.lock = threading.Lock()
        self.source = source
        self.directory = directory
        self.started_ns = started_ns
        self.offset = source.stat().st_size if source.exists() else 0
        self.identity = None
        if source.exists():
            stat = source.stat()
            self.identity = (stat.st_dev, stat.st_ino)
        self.count = 0
        self.observations = []
        self.truncated = False
        self.error = ""
        self.stop = threading.Event()
        self.target = directory / "logs/step.log"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.target.open("wb")
        self.thread = threading.Thread(target=self._run, name="replay-log", daemon=True)

    @classmethod
    def start(cls, workspace, step, directory: Path, started_ns: int):
        path = getattr(getattr(step, "log", None), "file", None)
        if not path:
            return None
        try:
            source = Path(path)
            if not source.is_absolute():
                source = Path(workspace.directory) / source
            # Validate even when the log has not been created yet.
            source = within(Path(workspace.directory), source.parent) / source.name
            if source.exists():
                within(Path(workspace.directory), source)
            capture = cls(source, directory, started_ns)
            capture.thread.start()
            return capture
        except (OSError, ValueError) as error:
            logger.warning("Replay log capture unavailable: %s", error)
            return None

    def poll(self):
        if not self.source.exists() or self.truncated:
            return
        stat = self.source.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self.identity is not None and (self.identity != identity or stat.st_size < self.offset):
            raise ValueError("Step log was replaced or truncated during capture")
        self.identity = identity
        # Bound each read and preserve the real output byte order, including UTF-8.
        end = stat.st_size
        with self.source.open("rb") as source:
            source.seek(self.offset)
            while self.offset < end and self.count < MAX_BYTES:
                data = source.read(min(1024 * 1024, end - self.offset, MAX_BYTES - self.count))
                if not data:
                    break
                self.stream.write(data)
                self.offset += len(data)
                self.count += len(data)
        self.truncated = self.offset < end and self.count >= MAX_BYTES
        if self.observations and self.observations[-1]["end_byte"] == self.count:
            return
        if self.count:
            self.observations.append(
                {
                    "elapsed_ns": max(0, time.monotonic_ns() - self.started_ns),
                    "end_byte": self.count,
                }
            )

    def _run(self):
        try:
            while not self.stop.wait(POLL_SECONDS):
                with self.lock:
                    self.poll()
            with self.lock:
                self.poll()
        except (OSError, ValueError) as error:
            self.error = str(error)

    def finish(self) -> dict:
        from chipcompiler.utility.log import flush_cstdio

        for stream in (sys.stdout, sys.stderr):
            with suppress(OSError, ValueError):
                stream.flush()
        flush_cstdio()
        self.stop.set()
        self.thread.join()
        self.stream.close()
        if self.error:
            logger.warning("Replay log capture unavailable: %s", self.error)
            return {"log_unavailable": self.error}
        index = {
            "schema": "ecos.replay.log.v1",
            "path": "logs/step.log",
            "time_basis": "observed_monotonic",
            "poll_interval_ns": int(POLL_SECONDS * 1_000_000_000),
            "truncated": self.truncated,
            "observations": self.observations,
        }
        atomic_json(self.directory / "logs/index.json", index)
        return {"log_index": "logs/index.json"}


active_log: ContextVar[LogCapture | None] = ContextVar("active_replay_log", default=None)
