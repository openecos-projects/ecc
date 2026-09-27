"""Strict line-record serialization for the two GUI catalog queries."""

import json
import math
import re
from collections.abc import Iterable, Mapping

MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_LINE_BYTES = 64 * 1024

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/+@-]+$")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class LineRecordError(ValueError):
    pass


def json_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def serialize_line_records(records: Iterable[Mapping[str, object]]) -> str:
    lines: list[str] = []
    size = 0
    for index, record in enumerate(records):
        if index >= MAX_RECORDS:
            raise LineRecordError(f"line record limit exceeds {MAX_RECORDS}")
        line = serialize_line_record(record)
        line_size = len(line.encode("utf-8"))
        if line_size > MAX_LINE_BYTES:
            raise LineRecordError(f"line record exceeds {MAX_LINE_BYTES} bytes")
        size += line_size + 1
        if size > MAX_OUTPUT_BYTES:
            raise LineRecordError(f"line record output exceeds {MAX_OUTPUT_BYTES} bytes")
        lines.append(line)
    return "".join(f"{line}\n" for line in lines)


def serialize_line_record(record: Mapping[str, object]) -> str:
    if not record or next(iter(record)) != "record":
        raise LineRecordError("record must be the first field")
    fields: list[str] = []
    for key, value in record.items():
        if not _KEY.fullmatch(key):
            raise LineRecordError(f"invalid line record key: {key!r}")
        if value is None:
            continue
        fields.append(f"{key}={_serialize_value(value)}")
    return " ".join(fields)


def _serialize_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LineRecordError("line records do not support non-finite numbers")
        return json.dumps(value, allow_nan=False)
    if not isinstance(value, str):
        raise LineRecordError(f"unsupported line record value: {type(value).__name__}")
    if _SAFE_VALUE.fullmatch(value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    if any(ord(character) < 0x20 for character in escaped):
        raise LineRecordError("line records contain an unsupported control character")
    return f'"{escaped}"'
