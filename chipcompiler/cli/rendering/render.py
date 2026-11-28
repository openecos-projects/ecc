import json
import math
import os
import sys

from chipcompiler.cli.core.types import CommandResult, OutputMode


def render_text(records: tuple[dict, ...], file=None) -> None:
    target = file or sys.stdout
    for record in records:
        parts = []
        for key, value in record.items():
            if value is None:
                continue
            display_key = key[:-4] if key.endswith("_cmd") else key
            if isinstance(value, str) and any(c.isspace() for c in value):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                parts.append(f'{display_key}="{escaped}"')
            else:
                parts.append(f"{display_key}={value}")
        print(" ".join(parts), file=target)


def render_plain(records: tuple[dict, ...], file=None) -> None:
    target = file or sys.stdout
    for record in records:
        parts = []
        for key, value in record.items():
            if value is None:
                continue
            parts.append(f"{key}={_plain_value(value)}")
        print(" ".join(parts), file=target)


def _json_value(value):
    """*value* as JSON can express it: a non-finite float inside a collection is null.

    ``json.dumps`` would write ``NaN`` and ``Infinity``, which a JSON parser rejects.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _plain_value(value) -> str:
    # Plain values are parsed, never evaluated: a boolean is written as in
    # JSON, and a list, tuple or mapping is written as JSON (#413).
    if isinstance(value, bool):
        s = "true" if value else "false"
    elif isinstance(value, (list, tuple, dict)):
        s = json.dumps(_json_value(value), ensure_ascii=False, allow_nan=False, default=str)
    else:
        s = str(value)
    if any(c.isspace() for c in s) or "\\" in s or '"' in s or "=" in s:
        # Plain output is one record per line: line breaks and tabs are
        # written as escapes, matching serialize_line_records (#407).
        escaped = (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    return s


def render_markdown(text: str, file=None, *, color: bool, pager: bool = False) -> None:
    from rich.console import Console
    from rich.markdown import Markdown

    # force_terminal tracks color: forcing a terminal on a colorless stream
    # makes rich 15 emit ANSI escapes even with no_color=True.
    console = Console(file=file or sys.stdout, force_terminal=color, no_color=not color)
    # Page only on a real terminal: pydoc picks its pager at import time, so
    # its own isatty check cannot be trusted once the process has been piped.
    if pager and file is None and sys.stdout.isatty():
        # pydoc invokes plain `less`, which escapes ANSI; with no user LESS,
        # default to git's FRX so styled output renders and short docs don't
        # open the pager UI at all.
        saved_less = os.environ.get("LESS")
        if saved_less is None:
            os.environ["LESS"] = "FRX"
        try:
            with console.pager(styles=color):
                console.print(Markdown(text))
        finally:
            if saved_less is None:
                del os.environ["LESS"]
    else:
        console.print(Markdown(text))


def render_result(
    result: CommandResult, mode: OutputMode, file=None, command=None, *, color=True
) -> None:
    if mode == OutputMode.JSON:
        print(
            json.dumps(list(result.records), ensure_ascii=False, indent=2), file=file or sys.stdout
        )
    elif mode == OutputMode.PLAIN:
        render_plain(result.records, file=file)
    elif mode == OutputMode.TEXT:
        _render_pretty(result, file=file, command=command, color=color)
    else:
        render_text(result.records, file=file)


def _render_pretty(result: CommandResult, file=None, command=None, *, color=True) -> None:
    from chipcompiler.cli.rendering.pretty import (
        render_error,
        render_generic_block,
    )

    records = result.records
    if not records:
        return

    first = records[0]

    if result.exit_code != 0 and first.get("kind") == "error":
        render_error(records, file=file, color=color)
        return

    # Command-specific pretty renderers dispatch via the RENDERERS registry
    # (keyed by full command path) before this fallback is reached.
    render_generic_block(records, file=file, color=color)
