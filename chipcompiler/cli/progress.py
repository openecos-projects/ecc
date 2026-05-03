import os
import re
import shutil
import threading
import time

from chipcompiler.cli.types import OutputMode


def should_enable_run_progress(ctx, stderr) -> bool:
    if ctx.output_mode != OutputMode.TEXT:
        return False
    return hasattr(stderr, "isatty") and stderr.isatty()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\r\n\t]+")
_MULTI_SPACE_RE = re.compile(r" {2,}")


def sanitize_log_line(line: str) -> str:
    stripped = _ANSI_RE.sub("", line)
    stripped = _CONTROL_RE.sub(" ", stripped)
    stripped = _MULTI_SPACE_RE.sub(" ", stripped)
    return stripped.strip()


def truncate_to_width(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def latest_log_line(path: str) -> str | None:
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


def terminal_width(fallback: int = 80) -> int:
    cols, _ = shutil.get_terminal_size(fallback=(fallback, 24))
    return max(cols, 1)


class RunProgressRenderer:
    def __init__(self, stream, width_fn=None):
        self._stream = stream
        self._width_fn = width_fn or terminal_width
        self._has_transient = False

    def running(self, text: str) -> None:
        width = self._width_fn()
        display = truncate_to_width(text, width)
        self._stream.write(f"\r\x1b[K{display}")
        self._stream.flush()
        self._has_transient = True

    def clear(self) -> None:
        if self._has_transient:
            self._stream.write("\r\x1b[K")
            self._stream.flush()
            self._has_transient = False

    def summary(self, text: str) -> None:
        self.clear()
        self._stream.write(f"{text}\n")
        self._stream.flush()


def _poll_log(renderer, log_path, step_token, tool, stop_event, interval=0.5):
    while not stop_event.is_set():
        line = latest_log_line(log_path)
        if line:
            renderer.running(f"  {step_token} ({tool}) | {line}")
        else:
            renderer.running(f"  {step_token} ({tool}) | waiting for log...")
        stop_event.wait(interval)


def run_flow_with_progress(engine_flow, ctx, project, stderr):
    from chipcompiler.data import StateEnum, log_flow

    from chipcompiler.cli.output import disclosure_cmd, normalize_step_name, normalize_state

    renderer = RunProgressRenderer(stderr)
    engine_flow.workspace.home.reset()

    for workspace_step in engine_flow.workspace_steps:
        step_token = normalize_step_name(workspace_step.name)
        tool = workspace_step.tool
        log_path = workspace_step.log.get("file", "")

        engine_flow.workspace.logger.log_section(
            f"{workspace_step.tool} - begin step - {workspace_step.name}"
        )

        stop_event = threading.Event()
        monitor = threading.Thread(
            target=_poll_log,
            args=(renderer, log_path, step_token, tool, stop_event),
            daemon=True,
        )
        monitor.start()

        start = time.time()

        state = engine_flow.run_step(workspace_step)

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

        status = normalize_state(state.value) if hasattr(state, "value") else str(state)

        rel_log = ""
        if log_path:
            try:
                rel_log = os.path.relpath(log_path, engine_flow.workspace.directory)
            except ValueError:
                rel_log = log_path

        inspect = disclosure_cmd(f"ecc log {step_token} --errors", project)

        renderer.summary(
            f"  step={step_token} tool={tool} status={status} "
            f"runtime={runtime} log={rel_log} inspect=\"{inspect}\""
        )

        if state != StateEnum.Success:
            return False

    return True
