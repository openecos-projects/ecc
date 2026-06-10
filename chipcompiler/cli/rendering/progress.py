import contextlib
import multiprocessing
import os
import re
import shutil
import sys
import threading
import time

from chipcompiler.cli.core.output import disclosure_cmd, normalize_state, normalize_step_name
from chipcompiler.cli.core.types import OutputMode
from chipcompiler.cli.inspection.log_view import (
    _KIND_COLOR,
    _KIND_LABEL,
    LineKind,
    extract_error_context,
)
from chipcompiler.cli.rendering.pretty import BOLD, CYAN, DIM, GREEN, RED, RESET
from chipcompiler.cli.rendering.pretty import style as _style
from chipcompiler.data import StateEnum, log_flow
from chipcompiler.utility.log import redirect_stdio_to_file


def supports_color(stream, mode, env=None):
    from chipcompiler.cli.rendering.pretty import supports_color as _supports_color

    return _supports_color(file=stream, mode=mode, env=env)


def style(text, code, enabled):
    return _style(text, code, enabled)


def should_enable_run_progress(ctx, stderr):
    if ctx.output_mode != OutputMode.TEXT:
        return False
    return hasattr(stderr, "isatty") and stderr.isatty()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")
_DCS_RE = re.compile(r"\x1bP.*?(?:\x1b\\)")
_CONTROL_RE = re.compile(r"[\r\n\t]+")
_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r" {2,}")
_LOG_POLL_INTERVAL = 0.5
_LOG_STALE_AFTER = 10.0


def sanitize_log_line(line):
    stripped = _OSC_RE.sub("", line)
    stripped = _DCS_RE.sub("", stripped)
    stripped = _ANSI_RE.sub("", stripped)
    stripped = _CONTROL_RE.sub(" ", stripped)
    stripped = _C0_RE.sub("", stripped)
    stripped = _MULTI_SPACE_RE.sub(" ", stripped)
    return stripped.strip()


def truncate_to_width(text, width):
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


# --- Failure context block formatting ---

_KIND_LABEL_COMPACT = {k: v.upper() for k, v in _KIND_LABEL.items()}


def format_error_context(log_path, context_lines, log_cmd, color=True):
    """Format a failure context block for interactive progress output.

    Args:
        log_path: Relative path to the failed step's log file.
        context_lines: List of LogLine objects from extract_error_context().
        log_cmd: Full disclosure command (e.g. 'ecc log synth --project p').
        color: Whether to emit ANSI color codes.
    """
    lines = []
    lines.append(f"error: {log_path}")

    if context_lines:
        max_no = max(ll.line_no for ll in context_lines)
        width = max(len(str(max_no)), 4)
    else:
        width = 4

    for ll in context_lines:
        no = str(ll.line_no).rjust(width)
        label = _KIND_LABEL_COMPACT[ll.kind]

        if color and ll.kind in _KIND_COLOR:
            code = _KIND_COLOR[ll.kind]
            if ll.kind == LineKind.ERROR:
                lines.append(f"  {no} {code}{label} {ll.text}{RESET}")
            else:
                lines.append(f"  {no} {code}{label}{RESET} {ll.text}")
        else:
            lines.append(f"  {no} {label} {ll.text}")

    lines.append(f"For more log info: {log_cmd}")
    lines.append(f'command="{log_cmd}"')
    return "\n".join(lines) + "\n"


def latest_log_line(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        sanitized = sanitize_log_line(line)
        if sanitized:
            return sanitized
    return None


class _IncrementalLogTail:
    def __init__(self, path, step_name, stale_after=10.0):
        self.path = path
        self.step_name = step_name
        self.stale_after = stale_after
        self.file_id = None
        self.change_id = None
        self.fingerprint = None
        self.head = None
        self.offset = 0
        self.partial = ""
        self.started_at = None
        self.last_line = None
        self.last_update_at = None

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        if self.started_at is None:
            self.started_at = now

        for line in self._read_new_lines():
            sanitized = sanitize_log_line(line)
            if sanitized:
                self.last_line = sanitized
                self.last_update_at = now

        if self.last_line is None:
            elapsed = max(0, now - self.started_at)
            return f"running {self.step_name}, waiting for step log {int(elapsed)}s..."

        elapsed = max(0, now - self.last_update_at)
        if elapsed >= self.stale_after:
            return f"running {self.step_name}, last log {int(elapsed)}s ago: {self.last_line}"

        return self.last_line

    def _read_new_lines(self):
        if not self.path or not os.path.isfile(self.path):
            return []

        try:
            stat = os.stat(self.path)
        except OSError:
            return []

        file_id = (stat.st_dev, stat.st_ino)
        change_id = (stat.st_mtime_ns, stat.st_ctime_ns)
        replaced = False
        if self.file_id == file_id and self.offset > 0:
            head = self._head()
            if stat.st_size < self.offset:
                replaced = True
            elif stat.st_size == self.offset:
                fingerprint = self._fingerprint(stat.st_size)
                replaced = fingerprint != self.fingerprint
            elif self.head is not None:
                compare_len = min(len(self.head), len(head), self.offset)
                replaced = head[:compare_len] != self.head[:compare_len]
        if self.file_id != file_id or replaced:
            self.file_id = file_id
            self.offset = 0
            self.partial = ""
        self.change_id = change_id

        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                f.seek(self.offset)
                chunk = f.read()
                self.offset = f.tell()
        except OSError:
            return []

        self.fingerprint = self._fingerprint(stat.st_size)
        self.head = self._head()
        if not chunk:
            return []

        text = self.partial + chunk
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.partial = lines.pop()
        else:
            self.partial = ""

        return lines

    def _head(self):
        if not self.path or not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "rb") as f:
                return f.read(4096)
        except OSError:
            return None

    def _fingerprint(self, size):
        if not self.path or not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "rb") as f:
                head = f.read(4096)
                if size > 4096:
                    f.seek(max(0, size - 4096))
                    tail = f.read(4096)
                else:
                    tail = b""
        except OSError:
            return None
        return size, head, tail


def terminal_width(fallback=80):
    cols, _ = shutil.get_terminal_size(fallback=(fallback, 24))
    return max(cols, 1)


def _stable_stream_from(stream):
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return stream

    try:
        dup_fd = os.dup(fd)
    except OSError:
        return stream

    encoding = getattr(stream, "encoding", None) or "utf-8"
    errors = getattr(stream, "errors", None)
    return os.fdopen(dup_fd, "w", encoding=encoding, errors=errors, buffering=1, closefd=True)


@contextlib.contextmanager
def _preserve_cli_stdio():
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = None
    saved_stderr_fd = None

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()

    try:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
    except OSError:
        if saved_stdout_fd is not None:
            os.close(saved_stdout_fd)
        try:
            yield
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
        return

    try:
        yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()

        try:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr


class RunProgressRenderer:
    def __init__(self, stream, width_fn=None, color=False):
        self._stream = stream
        self._width_fn = width_fn or terminal_width
        self._color = color
        self._has_transient = False
        self._step_started = False

    def running(self, text):
        width = self._width_fn()
        visible = truncate_to_width(f"  log: {text}", width)
        if self._color and visible.startswith("  log:"):
            visible = f"  {DIM}log:{RESET}{visible[6:]}"
        self._stream.write(f"\r\x1b[K{visible}")
        self._stream.flush()
        self._has_transient = True

    def clear(self):
        if self._has_transient:
            self._stream.write("\r\x1b[K\n")
            self._stream.flush()
            self._has_transient = False

    def start_run(self, name, workspace):
        self.clear()
        run_label = style("[run]", BOLD, self._color)
        self._stream.write(f"{run_label} {name} workspace={workspace}\n")
        self._stream.flush()

    def start_step(self, step, tool):
        self.clear()
        if self._step_started:
            self._stream.write("\n")
        header = style(f"> {step} ({tool})", CYAN, self._color)
        self._stream.write(f"{header}\n")
        self._stream.flush()
        self._step_started = True

    def finish_step(self, step, tool, status, runtime, log_path, inspect_cmd, success):
        self.clear()
        if success:
            line = style(f"✓ {step} ({tool}) {runtime}", GREEN, self._color)
        else:
            sym = style("✗", RED, self._color)
            status_styled = style(status, RED, self._color)
            line = f"{sym} {step} ({tool}) {status_styled} {runtime}"
        self._stream.write(f"{line}\n")
        log_label = style("  log:", DIM, self._color)
        self._stream.write(f"{log_label} {log_path}\n")
        inspect_label = style("  inspect:", DIM, self._color)
        self._stream.write(f"{inspect_label} {inspect_cmd}\n")
        self._stream.flush()

    def render_failure_context(self, block):
        """Write a pre-formatted failure context block to the progress stream."""
        self._stream.write(block)
        self._stream.flush()


def _monitor_log_progress(
    renderer,
    log_path,
    step_name,
    stop_event,
    interval=_LOG_POLL_INTERVAL,
    stale_after=_LOG_STALE_AFTER,
):
    tail = _IncrementalLogTail(log_path, step_name, stale_after=stale_after)
    while not stop_event.is_set():
        renderer.running(tail.poll())
        stop_event.wait(interval)


def _poll_log(renderer, log_path, stop_event, interval=_LOG_POLL_INTERVAL):
    _monitor_log_progress(renderer, log_path, "step", stop_event, interval=interval)


def _start_log_monitor(
    renderer,
    log_path,
    step_name,
    isolated=False,
    interval=_LOG_POLL_INTERVAL,
    stale_after=_LOG_STALE_AFTER,
):
    if isolated:
        ctx = multiprocessing.get_context("fork")
        stop_event = ctx.Event()
        monitor = ctx.Process(
            target=_monitor_log_progress,
            args=(renderer, log_path, step_name, stop_event),
            kwargs={"interval": interval, "stale_after": stale_after},
            daemon=True,
        )
    else:
        stop_event = threading.Event()
        monitor = threading.Thread(
            target=_monitor_log_progress,
            args=(renderer, log_path, step_name, stop_event),
            kwargs={"interval": interval, "stale_after": stale_after},
            daemon=True,
        )
    monitor.start()
    return stop_event, monitor


def _stop_log_monitor(stop_event, monitor, timeout=2.0):
    stop_event.set()
    monitor.join(timeout=timeout)
    if monitor.is_alive() and hasattr(monitor, "terminate"):
        monitor.terminate()
        monitor.join(timeout=timeout)


def run_flow_with_progress(engine_flow, ctx, project, stderr):
    color = supports_color(stderr, ctx.output_mode)
    progress_stream = _stable_stream_from(stderr)
    try:
        renderer = RunProgressRenderer(progress_stream, color=color)
        engine_flow.workspace.home.reset()

        run_dir = engine_flow.workspace.directory
        run_name = os.path.basename(run_dir) or "default"
        renderer.start_run(run_name, run_dir)

        for workspace_step in engine_flow.workspace_steps:
            step_token = normalize_step_name(workspace_step.name)
            tool = workspace_step.tool
            log_path = workspace_step.log.get("file", "")

            engine_flow.workspace.logger.log_section(
                f"{workspace_step.tool} - begin step - {workspace_step.name}"
            )

            renderer.start_step(step_token, tool)
            renderer.running("starting step...")

            stop_event, monitor = _start_log_monitor(
                renderer,
                log_path,
                step_token,
                isolated=progress_stream is not stderr,
            )

            start = time.time()

            try:
                with _preserve_cli_stdio():
                    if not engine_flow.check_state(
                        name=workspace_step.name,
                        tool=workspace_step.tool,
                        state=StateEnum.Success,
                    ):
                        init_log_stream = None
                        if log_path:
                            try:
                                abs_log_path = os.path.abspath(log_path)
                                os.makedirs(os.path.dirname(abs_log_path) or ".", exist_ok=True)
                                init_log_stream = redirect_stdio_to_file(abs_log_path)
                            except OSError:
                                init_log_stream = None
                        try:
                            engine_flow.init_db_engine()
                        finally:
                            if init_log_stream is not None:
                                init_log_stream.close()
                    state = engine_flow.run_step(workspace_step)
            finally:
                _stop_log_monitor(stop_event, monitor)
                renderer.clear()

            log_flow(workspace=engine_flow.workspace)
            engine_flow.workspace.logger.log_section(
                f"{workspace_step.tool} - end step - {workspace_step.name}"
            )

            elapsed = time.time() - start
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            runtime = f"{hours}:{minutes:02d}:{seconds:02d}"

            status = normalize_state(state.value)

            rel_log = ""
            if log_path:
                try:
                    rel_log = os.path.relpath(log_path, engine_flow.workspace.directory)
                except ValueError:
                    rel_log = log_path

            inspect = disclosure_cmd(f"ecc log {step_token}", project)

            is_success = state == StateEnum.Success
            renderer.finish_step(step_token, tool, status, runtime, rel_log, inspect, is_success)

            if not is_success:
                _maybe_render_failure_context(
                    renderer, log_path, rel_log, step_token, project, ctx.run_id, color
                )
                return False

        return True
    finally:
        if progress_stream is not stderr:
            progress_stream.close()


def _maybe_render_failure_context(renderer, log_path, rel_log, step_token, project, run_id, color):
    if not log_path or not os.path.isfile(log_path):
        return
    try:
        with open(log_path, errors="replace") as f:
            raw = f.read()
    except OSError:
        return
    log_lines = raw.splitlines()
    if not log_lines:
        return

    ctx_lines = extract_error_context(log_lines)
    full_cmd = disclosure_cmd(f"ecc log {step_token}", project, run_id)
    block = format_error_context(rel_log, ctx_lines, full_cmd, color=color)
    renderer.render_failure_context(block)
