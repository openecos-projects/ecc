import os
import re
import shutil
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


def supports_color(stream, mode, env=None):
    from chipcompiler.cli.rendering.pretty import supports_color as _supports_color

    return _supports_color(file=stream, mode=mode, env=env)


def style(text, code, enabled):
    return _style(text, code, enabled=enabled)


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
_LIVE_LINE_MIN_INTERVAL = 0.1


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


def format_error_context(log_path, context_lines, log_cmd, *, color=True):
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


class RunProgressRenderer:
    def __init__(self, stream, width_fn=None, *, color=False):
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


def run_flow_with_progress(workspace_dir, ctx, project, stderr, run_operation):
    """Render TTY progress for a worker-driven flow execution.

    run_operation receives the reader callbacks (on_output, on_step_event)
    and returns an OperationResult. Step transitions and the live log line
    are driven by those callbacks; per-step final states are refreshed from
    flow.json on each begin marker and once more when the operation ends.
    """
    color = supports_color(stderr, ctx.output_mode)
    progress_stream = _stable_stream_from(stderr)
    try:
        renderer = RunProgressRenderer(progress_stream, color=color)
        run_name = ctx.run_id or "default"
        renderer.start_run(run_name, workspace_dir)

        from chipcompiler.runtime.log_stream import step_log_archive_resolver

        resolve_log = step_log_archive_resolver(workspace_dir)
        rendered = set()
        live = {"written_at": 0.0}

        def on_output(data: bytes) -> None:
            now = time.monotonic()
            if now - live["written_at"] < _LIVE_LINE_MIN_INTERVAL:
                return
            text = sanitize_log_line(data.decode("utf-8", errors="replace"))
            if not text:
                return
            live["written_at"] = now
            renderer.running(text)

        def refresh_final_states() -> None:
            from chipcompiler.cli.inspection.discovery import CORRUPT_FLOW_JSON, read_flow_json

            flow_data = read_flow_json(workspace_dir)
            if flow_data is None or flow_data is CORRUPT_FLOW_JSON:
                return
            for record in flow_data.get("steps", []):
                if not isinstance(record, dict):
                    continue
                name = record.get("name")
                tool = record.get("tool") or ""
                state = record.get("state")
                if not name or (name, tool) in rendered:
                    continue
                if state not in ("Success", "Imcomplete", "Incomplete", "Invalid"):
                    continue
                rendered.add((name, tool))
                runtime = record.get("runtime") or "0:00:00"
                step_token = normalize_step_name(name)
                log_path = str(resolve_log(name, tool))
                try:
                    rel_log = os.path.relpath(log_path, workspace_dir)
                except ValueError:
                    rel_log = log_path
                inspect = disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id)
                success = state == "Success"
                renderer.finish_step(
                    step_token,
                    tool,
                    normalize_state(state),
                    runtime,
                    rel_log,
                    inspect,
                    success,
                )
                if not success:
                    _maybe_render_failure_context(
                        renderer, log_path, rel_log, step_token, project, ctx.run_id, color
                    )

        def on_step_event(event: str, step: str, tool: str) -> None:
            if event != "begin":
                return
            # The previous step's final state is persisted before this begin
            # marker is written, so flow.json already reflects it here.
            refresh_final_states()
            renderer.start_step(normalize_step_name(step), tool)
            renderer.running("starting step...")

        result = run_operation(on_output=on_output, on_step_event=on_step_event)
        refresh_final_states()
        renderer.clear()
        return result
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
