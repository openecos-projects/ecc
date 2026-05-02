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
                escaped = value.replace('\\', '\\\\').replace('"', '\\"')
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


def render_result(result: CommandResult, mode: OutputMode, file=None) -> None:
    if mode == OutputMode.JSON:
        render_json(result, file=file)
    elif mode == OutputMode.JSONL:
        render_jsonl(result, file=file)
    else:
        render_text(result.records, file=file)
