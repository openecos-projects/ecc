import os
import sys

from chipcompiler.cli.core.types import OutputMode

# --- ANSI constants ---

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"

# --- Color gating ---


def supports_color(file=None, env=None, mode=None):
    if env is None:
        env = os.environ
    if mode is not None and mode != OutputMode.TEXT:
        return False
    target = file or sys.stdout
    if not hasattr(target, "isatty") or not target.isatty():
        return False
    if env.get("NO_COLOR") is not None:
        return False
    return env.get("TERM", "") != "dumb"


def style(text, code, *, enabled=True):
    if not enabled:
        return text
    return f"{code}{text}{RESET}"


# --- Display key normalization ---


def display_key(key):
    k = key[:-4] if key.endswith("_cmd") else key
    return k.replace("_", " ")


# --- Value formatting ---


# --- Pretty block rendering ---


def render_header(tag, *, color=True):
    return style(f"[{tag}]", BOLD, enabled=color)


def render_field(label, value, *, color=True, dim_label=False):
    if dim_label:
        return f"  {style(label + ':', DIM, enabled=color)} {value}"
    return f"  {label}: {value}"


def render_generic_block(records, file=None, *, color=True, tag=None):
    """Render records as a generic pretty block."""
    target = file or sys.stdout
    first = records[0] if records else {}

    header_tag = tag or _infer_tag(first)
    target.write(f"{render_header(header_tag, color=color)}\n")

    for record in records:
        for key, value in record.items():
            if value is None:
                continue
            dk = display_key(key)
            target.write(f"  {dk}: {value}\n")

    target.write("\n")


def _infer_tag(record):
    for key in ("status", "run", "project", "kind"):
        if key in record:
            return key
    return "result"


# --- Status-specific color helpers ---

_STATUS_COLORS = {
    "success": GREEN,
    "clean": GREEN,
    "checked": GREEN,
    "created": GREEN,
    "pass": GREEN,
    "set": GREEN,
    "failed": RED,
    "fail": RED,
    "missing": RED,
    "corrupt": RED,
    "error": RED,
    "unknown_step": RED,
    "invalid": RED,
    "warning": YELLOW,
    "incomplete": YELLOW,
    "ongoing": YELLOW,
    "pending": YELLOW,
}


def status_style(status_text, *, color=True):
    code = _STATUS_COLORS.get(status_text)
    if code and color:
        return style(status_text, code, enabled=True)
    return status_text


# --- Command-specific pretty renderers ---


def render_init(records, file=None, *, color=True):
    target = file or sys.stdout
    r = records[0]
    target.write(f"{render_header('init', color=color)}\n")
    target.write(f"  project: {r.get('project', '')}\n")
    target.write(f"  status: {status_style(r.get('status', ''), color=color)}\n")
    target.write(f"  path: {r.get('path', '')}\n")
    _render_disclosure_fields(target, r, color)
    target.write("\n")


def render_check(records, file=None, *, color=True):
    target = file or sys.stdout
    first = records[0]

    if first.get("kind") == "error" or first.get("status") == "fail":
        target.write(f"{render_header('check', color=color)}\n")
        for r in records:
            reason = r.get("reason", r.get("error", ""))
            target.write(f"  {status_style('fail', color=color)} {reason}\n")
            if r.get("inspect"):
                target.write(
                    render_field("inspect", r["inspect"], color=color, dim_label=True) + "\n"
                )
        target.write("\n")
        return

    target.write(f"{render_header('check', color=color)}\n")
    r = records[0]
    target.write(f"  project: {r.get('project', '')}\n")
    target.write(f"  status: {status_style(r.get('status', ''), color=color)}\n")
    target.write(f"  config: {r.get('config', '')}\n")
    _render_disclosure_fields(target, r, color)

    for r in records[1:]:
        label = r.get("check", "")
        st = r.get("status", "")
        target.write(f"  {label}: {status_style(st, color=color)}\n")
        if r.get("path"):
            target.write(f"    path: {r['path']}\n")
        if r.get("inspect"):
            target.write(render_field("inspect", r["inspect"], color=color, dim_label=True) + "\n")

    target.write("\n")


def render_run_summary(records, file=None, *, color=True):
    target = file or sys.stdout
    r = records[0]
    st = r.get("status", "")
    tag = "run"
    target.write(f"{render_header(tag, color=color)}\n")
    target.write(f"  run: {r.get('run', '')}\n")
    target.write(f"  status: {status_style(st, color=color)}\n")
    target.write(f"  workspace: {r.get('workspace', '')}\n")
    _render_disclosure_fields(target, r, color)
    target.write("\n")


def render_status(records, file=None, *, color=True):
    target = file or sys.stdout
    first = records[0]

    if first.get("kind") == "error":
        render_generic_block(records, file=file, color=color, tag="status")
        return

    st = first.get("status", "")
    target.write(f"{render_header('status', color=color)}\n")
    target.write(f"  run: {first.get('run', '')}\n")
    target.write(f"  status: {status_style(st, color=color)}\n")
    if first.get("workspace"):
        target.write(f"  workspace: {first['workspace']}\n")
    _render_disclosure_fields(target, first, color)

    step_records = [r for r in records if "step" in r]
    if step_records:
        target.write("\n")
        target.write(
            f"  {style('steps', CYAN if color else None, enabled=color)}:\n"
            if color
            else "  steps:\n"
        )
        for r in step_records:
            step = r.get("step", "")
            tool = r.get("tool", "")
            st = r.get("status", "")
            runtime = r.get("runtime", "") or ""
            step_label = style(step, CYAN, enabled=color) if color else step
            status_label = status_style(st, color=color)
            line = f"    {step_label} ({tool}) {status_label}"
            if runtime:
                line += f" {runtime}"
            target.write(f"{line}\n")
            _render_step_disclosure(target, r, color)

    target.write("\n")


def render_config(records, file=None, *, color=True):
    target = file or sys.stdout
    first = records[0]

    if first.get("kind") == "error":
        render_generic_block(records, file=file, color=color, tag="config")
        return

    if first.get("config_status") == "none":
        target.write(f"{render_header('config', color=color)}\n")
        msg = (
            f"  No configuration for step {first.get('step', '')}.\n"
            if first.get("step")
            else "  No configuration found.\n"
        )
        target.write(msg)
        target.write("\n")
        return

    target.write(f"{render_header('config', color=color)}\n")

    current_scope = None
    for r in records:
        scope = r.get("scope", "")
        if scope != current_scope:
            if current_scope is not None:
                target.write("\n")
            current_scope = scope
            scope_label = style(scope, CYAN, enabled=color) if color else scope
            target.write(f"  {scope_label}:\n")

        config = r.get("config", r.get("key", ""))
        value = r.get("value", "")
        source = r.get("source", "")

        if r.get("kind") == "param":
            target.write(f"    {config}: {value}")
            if source and source != "default":
                target.write(f"  ({source})")
            target.write("\n")
        elif scope == "step":
            target.write(f"    {config} ({r.get('role', '')})\n")
            target.write(f"      path: {r.get('path', '')}\n")
        else:
            target.write(f"    {config}: {value}")
            if source:
                target.write(f"  ({source})")
            target.write("\n")

        if r.get("inspect"):
            target.write(render_field("inspect", r["inspect"], color=color, dim_label=True) + "\n")

    target.write("\n")


def render_error(records, file=None, *, color=True):
    target = file or sys.stdout
    target.write(f"{render_header('error', color=color)}\n")
    for record in records:
        error = record.get("error", record.get("kind", "error"))
        reason = record.get("reason", "")
        target.write(f"  {style(error, RED, enabled=color)}")
        if reason:
            target.write(f" {reason}")
        target.write("\n")
        for key, value in record.items():
            if key in ("kind", "error", "reason"):
                continue
            if value is None:
                continue
            dk = display_key(key)
            target.write(render_field(dk, value, color=color, dim_label=True) + "\n")
    target.write("\n")


# --- Internal helpers ---


def _render_disclosure_fields(target, record, color):
    for key in sorted(record.keys()):
        if not key.endswith("_cmd") and key not in (
            "inspect",
            "check",
            "run",
            "start_cmd",
            "log",
            "config",
        ):
            continue
        value = record.get(key)
        if not value:
            continue
        label = display_key(key)
        target.write(render_field(label, value, color=color, dim_label=True) + "\n")


def _render_step_disclosure(target, record, color, indent="      "):
    for key in ("log_cmd", "log", "config", "start_cmd", "inspect"):
        value = record.get(key)
        if not value:
            continue
        label = display_key(key)
        dim_label = style(f"{label}:", DIM, enabled=color) if color else f"{label}:"
        target.write(f"{indent}{dim_label} {value}\n")


# --- Renderer registry ---


def get_pretty_renderer(command):
    registry = {
        "init": render_init,
        "check": render_check,
        "run": render_run_summary,
        "status": render_status,
        "config": render_config,
    }
    return registry.get(command)
