"""Step marker protocol and log stream archive.

The worker emits step markers on stderr using a Record Separator prefix:
    \\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\\n
    \\x1eECC-STEP {"v":1,"event":"end","step":"Synthesis","tool":"yosys"}\\n

The client-side LogStreamReader drains worker stderr, parses markers to
switch between step log files, and archives raw tool bytes to the correct
step log path.
"""

import json
import os
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from chipcompiler.utility.path import path_is_within

MARKER_PREFIX = b"\x1eECC-STEP "
MARKER_VERSION = 1


@dataclass
class StepMarker:
    event: str
    step: str
    tool: str


def emit_step_marker(event: str, step: str, tool: str) -> None:
    """Write a step marker to stderr using a single os.write() call."""
    import sys

    from chipcompiler.utility.log import flush_cstdio

    sys.stdout.flush()
    sys.stderr.flush()
    # C/C++ buffers must drain before the marker, or pending native output
    # lands on the wrong side of the step boundary.
    flush_cstdio()
    payload = json.dumps(
        {"v": MARKER_VERSION, "event": event, "step": step, "tool": tool},
        separators=(",", ":"),
    )
    line = MARKER_PREFIX + payload.encode("utf-8") + b"\n"
    os.write(2, line)


def step_log_archive_resolver(workspace_dir) -> Callable[[str, str], Path]:
    """Resolve the archive path for a step's tool log inside a workspace."""
    base = Path(workspace_dir)

    def resolve(step: str, tool: str) -> Path:
        return base / f"{step}_{tool}" / "log" / f"{step}.log"

    return resolve


def parse_marker(line: bytes) -> StepMarker | None:
    """Parse a complete line as a step marker, or return None if invalid."""
    if not line.startswith(MARKER_PREFIX):
        return None
    payload = line[len(MARKER_PREFIX) :]
    if payload.endswith(b"\n"):
        payload = payload[:-1]
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("v")
    # JSON true/false are bool in Python; bool == 1 is True, so exclude it.
    if isinstance(version, bool) or version != MARKER_VERSION:
        return None
    event = data.get("event")
    step = data.get("step")
    tool = data.get("tool")
    if not isinstance(event, str) or not isinstance(step, str) or not isinstance(tool, str):
        return None
    return StepMarker(event=event, step=step, tool=tool)


@dataclass
class LogStreamState:
    """Mutable state maintained by the log stream reader."""

    tail_bytes: bytes = b""
    archive_file: BinaryIO | None = field(default=None, repr=False)
    active_step: str | None = None
    active_tool: str | None = None
    bytes_archived: int = 0
    steps_seen: list[str] = field(default_factory=list)
    error: Exception | None = None


class LogStreamReader:
    """Drains worker stderr, parses markers, and archives raw bytes to step logs.

    The reader runs in a dedicated thread. Marker lines are consumed (not archived).
    Non-marker bytes are written to the current step's log file. A callback is
    invoked for display purposes with the decoded text.
    """

    def __init__(
        self,
        stderr: BinaryIO,
        *,
        log_path_resolver: Callable[[str, str], Path | None] | None = None,
        on_output: Callable[[bytes], None] | None = None,
        on_step_event: Callable[[str, str, str], None] | None = None,
        tail_size: int = 4096,
        valid_steps: set[tuple[str, str]] | None = None,
        workspace_dir: Path | None = None,
    ):
        self._stderr = stderr
        self._resolve_path = log_path_resolver
        self._on_output = on_output
        self._on_output_disabled = False
        self._on_step_event = on_step_event
        self._on_step_event_disabled = False
        self._tail_size = tail_size
        self._valid_steps = valid_steps
        self._workspace_dir = workspace_dir
        self._state = LogStreamState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def state(self) -> LogStreamState:
        return self._state

    def _record_error(self, exc: Exception) -> None:
        if self._state.error is None:
            self._state.error = exc

    def start(self) -> None:
        self._thread = threading.Thread(target=self._drain_loop, name="ecc-log-reader", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def completed(self) -> bool:
        """True if the drain thread has finished (or was never started)."""
        if self._thread is None:
            return True
        return not self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()

    def _drain_loop(self) -> None:
        buf = b""
        try:
            while not self._stop.is_set():
                chunk = self._stderr.read(8192)
                if not chunk:
                    break
                buf += chunk
                buf = self._process_buffer(buf)
            if buf:
                self._emit_data(buf)
        except Exception as exc:
            self._state.error = exc
        finally:
            self._close_archive()

    def _process_buffer(self, buf: bytes) -> bytes:
        while True:
            idx = buf.find(MARKER_PREFIX)
            if idx < 0:
                # No candidate frame: hold back only a trailing partial prefix.
                tail = buf.rfind(MARKER_PREFIX[:1])
                if tail >= 0 and MARKER_PREFIX.startswith(buf[tail:]):
                    if tail:
                        self._emit_data(buf[:tail])
                    return buf[tail:]
                if buf:
                    self._emit_data(buf)
                return b""
            if idx > 0:
                # Bytes before a marker candidate are ordinary stream data.
                self._emit_data(buf[:idx])
                buf = buf[idx:]
                continue
            nl = buf.find(b"\n")
            if nl < 0:
                if len(buf) < 512:
                    return buf
                # An overlong candidate without a newline is not a marker:
                # emit the prefix's first byte and rescan the remainder.
                self._emit_data(buf[:1])
                buf = buf[1:]
                continue
            frame = buf[: nl + 1]
            marker = parse_marker(frame)
            if marker is not None:
                self._handle_marker(marker, frame)
            else:
                self._emit_data(frame)
            buf = buf[nl + 1 :]

    def _is_allowed_step(self, step: str, tool: str) -> bool:
        if self._valid_steps is None:
            return True
        return (step, tool) in self._valid_steps

    def _validated_archive_path(self, step: str, tool: str) -> Path | None:
        """Resolve and validate the archive path for a begin marker.

        Returns the validated path, or None when archiving is not configured
        (resolver absent) or when the marker must degrade to ordinary bytes
        (unsafe names, resolver failure, containment violation).
        """
        if self._resolve_path is None:
            return None
        for value in (step, tool):
            if not value or "/" in value or "\\" in value or ".." in value:
                self._record_error(ValueError(f"unsafe step marker name: {value!r}"))
                return None
        try:
            path = self._resolve_path(step, tool)
        except Exception as exc:
            self._record_error(exc)
            return None
        if path is None:
            return None
        if self._workspace_dir is not None and not path_is_within(path, self._workspace_dir):
            self._record_error(ValueError(f"archive path escapes workspace: {path}"))
            return None
        return path

    def _handle_marker(self, marker: StepMarker, raw_line: bytes) -> None:
        if marker.event == "begin":
            if not self._is_allowed_step(marker.step, marker.tool):
                self._emit_data(raw_line)
                return
            if self._state.active_step is not None:
                self._emit_data(raw_line)
                return
            archive_path = self._validated_archive_path(marker.step, marker.tool)
            if self._resolve_path is not None and archive_path is None:
                self._emit_data(raw_line)
                return
            self._state.active_step = marker.step
            self._state.active_tool = marker.tool
            self._state.steps_seen.append(marker.step)
            if archive_path is not None:
                self._open_archive(archive_path)
            self._emit_step_event("begin", marker.step, marker.tool)
        elif marker.event == "end":
            if marker.step == self._state.active_step and marker.tool == self._state.active_tool:
                self._close_archive()
                self._state.active_step = None
                self._state.active_tool = None
                self._emit_step_event("end", marker.step, marker.tool)
            else:
                self._emit_data(raw_line)
        else:
            self._emit_data(raw_line)

    def _emit_step_event(self, event: str, step: str, tool: str) -> None:
        if self._on_step_event is None or self._on_step_event_disabled:
            return
        try:
            self._on_step_event(event, step, tool)
        except Exception as exc:
            self._record_error(exc)
            self._on_step_event_disabled = True

    def _emit_data(self, data: bytes) -> None:
        if self._state.archive_file is not None:
            try:
                self._state.archive_file.write(data)
                self._state.bytes_archived += len(data)
            except OSError as exc:
                self._record_error(exc)
                with suppress(OSError):
                    self._state.archive_file.close()
                self._state.archive_file = None
        self._update_tail(data)
        if self._on_output is not None and not self._on_output_disabled:
            try:
                self._on_output(data)
            except Exception as exc:
                self._record_error(exc)
                self._on_output_disabled = True

    def _update_tail(self, data: bytes) -> None:
        combined = self._state.tail_bytes + data
        if len(combined) > 2 * self._tail_size:
            combined = combined[-self._tail_size :]
        self._state.tail_bytes = combined

    def _open_archive(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._state.archive_file = path.open("wb")  # noqa: SIM115
        except OSError as exc:
            self._record_error(exc)
            self._state.archive_file = None

    def _close_archive(self) -> None:
        if self._state.archive_file is not None:
            try:
                self._state.archive_file.flush()
            except OSError as exc:
                self._record_error(exc)
            finally:
                try:
                    self._state.archive_file.close()
                except OSError as exc:
                    self._record_error(exc)
                self._state.archive_file = None
