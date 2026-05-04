import os
import re
import shutil
import threading
import time

from chipcompiler.cli.types import OutputMode

_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_RESET = "\x1b[0m"


def supports_color(stream, mode, env=None):
    if env is None:
        env = os.environ
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if mode != OutputMode.TEXT:
        return False
    if env.get("NO_COLOR") is not None:
        return False
    if env.get("TERM", "") == "dumb":
        return False
    return True


def style(text, code, enabled):
    if not enabled:
        return text
    return f"{code}{text}{_RESET}"


def should_enable_run_progress(ctx, stderr):
    if ctx.output_mode != OutputMode.TEXT:
        return False
    return hasattr(stderr, "isatty") and stderr.isatty()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\r\n\t]+")
_MULTI_SPACE_RE = re.compile(r" {2,}")


def sanitize_log_line(line):
    stripped = _ANSI_RE.sub("", line)
    stripped = _CONTROL_RE.sub(" ", stripped)
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


def latest_log_line(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        sanitized = sanitize_log_line(line)
        if sanitized:
            return sanitized
    return None


def terminal_width(fallback=80):
    cols, _ = shutil.get_terminal_size(fallback=(fallback, 24))
    return max(cols, 1)


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
            visible = f"  {_DIM}log:{_RESET}{visible[6:]}"
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
        run_label = style("[run]", _BOLD, self._color)
        self._stream.write(f"{run_label} {name} workspace={workspace}\n")
        self._stream.flush()

    def start_step(self, step, tool):
        self.clear()
        if self._step_started:
            self._stream.write("\n")
        header = style(f"> {step} ({tool})", _CYAN, self._color)
        self._stream.write(f"{header}\n")
        self._stream.flush()
        self._step_started = True

    def finish_step(self, step, tool, status, runtime, log_path, inspect_cmd, success):
        self.clear()
        if success:
            line = style(f"✓ {step} ({tool}) {runtime}", _GREEN, self._color)
        else:
            sym = style("✗", _RED, self._color)
            status_styled = style(status, _RED, self._color)
            line = f"{sym} {step} ({tool}) {status_styled} {runtime}"
        self._stream.write(f"{line}\n")
        log_label = style("  log:", _DIM, self._color)
        self._stream.write(f"{log_label} {log_path}\n")
        inspect_label = style("  inspect:", _DIM, self._color)
        self._stream.write(f"{inspect_label} {inspect_cmd}\n")
        self._stream.flush()


def _poll_log(renderer, log_path, stop_event, interval=0.5):
    while not stop_event.is_set():
        line = latest_log_line(log_path)
        renderer.running(line or "waiting for log...")
        stop_event.wait(interval)


def run_flow_with_progress(engine_flow, ctx, project, stderr):
    from chipcompiler.data import StateEnum, log_flow

    from chipcompiler.cli.output import disclosure_cmd, normalize_step_name, normalize_state

    color = supports_color(stderr, ctx.output_mode)
    renderer = RunProgressRenderer(stderr, color=color)
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

        stop_event = threading.Event()
        monitor = threading.Thread(
            target=_poll_log,
            args=(renderer, log_path, stop_event),
            daemon=True,
        )
        monitor.start()

        start = time.time()

        try:
            state = engine_flow.run_step(workspace_step)
        finally:
            stop_event.set()
            monitor.join(timeout=2.0)
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
            return False

    return True
