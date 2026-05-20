import json
import sys

from chipcompiler.cli.types import CommandResult, OutputMode


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


def render_json(result: CommandResult, file=None) -> None:
    target = file or sys.stdout
    print(json.dumps({"records": list(result.records)}, ensure_ascii=False), file=target)


def render_jsonl(result: CommandResult, file=None) -> None:
    target = file or sys.stdout
    for record in result.records:
        print(json.dumps(record, ensure_ascii=False), file=target)


def render_plain(records: tuple[dict, ...], file=None) -> None:
    target = file or sys.stdout
    for record in records:
        parts = []
        for key, value in record.items():
            if value is None:
                continue
            parts.append(f"{key}={_plain_value(value)}")
        print(" ".join(parts), file=target)


def _plain_value(value) -> str:
    s = str(value)
    if any(c.isspace() for c in s) or "\\" in s or '"' in s or "=" in s:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def render_result(
    result: CommandResult, mode: OutputMode, file=None, command=None, color=True
) -> None:
    if mode == OutputMode.JSON:
        render_json(result, file=file)
    elif mode == OutputMode.JSONL:
        render_jsonl(result, file=file)
    elif mode == OutputMode.PLAIN:
        render_plain(result.records, file=file)
    elif mode == OutputMode.TEXT:
        _render_pretty(result, file=file, command=command, color=color)
    else:
        render_text(result.records, file=file)


def _render_pretty(result: CommandResult, file=None, command=None, color=True) -> None:
    from chipcompiler.cli.pretty import (
        get_pretty_renderer,
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

    renderer = get_pretty_renderer(command) if command else None
    if renderer:
        renderer(records, file=file, color=color)
    else:
        render_generic_block(records, file=file, color=color)
