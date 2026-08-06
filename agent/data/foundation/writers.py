from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Mapping[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]], *, sort_keys: bool = True) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=sort_keys))
            handle.write("\n")
            count += 1
    return count


def write_parquet(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    columns: Iterable[str] | None = None,
    schema: Any | None = None,
    batch_size: int = 2048,
) -> int:
    """Write records as a Parquet table and return the number of rows.

    ``pyarrow`` is intentionally imported lazily so callers get a clear runtime
    error when the formal Parquet dependency is missing.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised in dependency setup failures
        raise RuntimeError(
            "pyarrow is required to write foundation_data/ecc Parquet tables"
        ) from exc

    column_names = tuple(columns or ())
    normalized_batch_size = max(1, int(batch_size))
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    writer = None
    active_schema = schema
    batch: list[dict[str, Any]] = []
    initial_schema_scan_limit = max(normalized_batch_size, normalized_batch_size * 4)

    def normalize(record: Mapping[str, Any]) -> dict[str, Any]:
        if column_names:
            return {column: record.get(column) for column in column_names}
        return dict(record)

    def coerce_value_for_type(value: Any, field_type) -> Any:
        if value is None:
            return None
        if pa.types.is_string(field_type):
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if pa.types.is_integer(field_type) and isinstance(value, bool):
            return int(value)
        if pa.types.is_floating(field_type) and isinstance(value, bool):
            return float(value)
        return value

    def coerce_rows_to_schema(rows: list[dict[str, Any]], target_schema) -> list[dict[str, Any]]:
        coerced = []
        for row in rows:
            normalized = {}
            for field in target_schema:
                normalized[field.name] = coerce_value_for_type(row.get(field.name), field.type)
            coerced.append(normalized)
        return coerced

    def flush(current_batch: list[dict[str, Any]]) -> None:
        nonlocal writer, row_count, active_schema
        if not current_batch:
            return
        if active_schema is not None and writer is None:
            writer = pq.ParquetWriter(path, active_schema)
        if active_schema is not None:
            table = pa.Table.from_pylist(
                coerce_rows_to_schema(current_batch, active_schema),
                schema=active_schema,
            )
            writer.write_table(table)
            row_count += len(current_batch)
            return
        current_schema = pa.Table.from_pylist(current_batch).schema
        if writer is None:
            active_schema = current_schema
            writer = pq.ParquetWriter(path, active_schema)
        else:
            merged_schema = merge_schemas(active_schema, current_schema)
            if merged_schema != active_schema:
                reopen_writer_with_schema(merged_schema)
        table = pa.Table.from_pylist(
            coerce_rows_to_schema(current_batch, active_schema),
            schema=active_schema,
        )
        writer.write_table(table)
        row_count += len(current_batch)

    def merge_types(left, right):
        if left == right:
            return left
        if pa.types.is_null(left):
            return right
        if pa.types.is_null(right):
            return left
        if pa.types.is_integer(left) and pa.types.is_integer(right):
            return pa.int64()
        if (pa.types.is_integer(left) or pa.types.is_floating(left)) and (
            pa.types.is_integer(right) or pa.types.is_floating(right)
        ):
            return pa.float64()
        return pa.string()

    def merge_schemas(left, right):
        fields = []
        right_names = set(right.names)
        for field in left:
            if field.name in right_names:
                fields.append(
                    pa.field(field.name, merge_types(field.type, right.field(field.name).type))
                )
            else:
                fields.append(field)
        left_names = set(left.names)
        for field in right:
            if field.name not in left_names:
                fields.append(field)
        return pa.schema(fields)

    def reopen_writer_with_schema(schema) -> None:
        nonlocal writer, active_schema
        if writer is not None:
            writer.close()
            writer = None
        existing_rows = pq.read_table(path).to_pylist() if row_count else []
        active_schema = schema
        writer = pq.ParquetWriter(path, active_schema)
        if existing_rows:
            writer.write_table(
                pa.Table.from_pylist(
                    coerce_rows_to_schema(existing_rows, active_schema),
                    schema=active_schema,
                )
            )

    def has_null_typed_fields(rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return False
        table = pa.Table.from_pylist(rows)
        return any(pa.types.is_null(field.type) for field in table.schema)

    def coerce_null_schema_rows(rows: list[dict[str, Any]]):
        inferred = pa.Table.from_pylist(rows)
        schema = pa.schema(
            [
                pa.field(field.name, pa.string()) if pa.types.is_null(field.type) else field
                for field in inferred.schema
            ]
        )
        return pa.Table.from_pylist(rows, schema=schema)

    def initial_schema_for_rows(rows: list[dict[str, Any]]):
        if schema is not None:
            return schema
        names = list(column_names or dict.fromkeys(key for row in rows for key in row))
        fields = []
        for name in names:
            values = [row.get(name) for row in rows if row.get(name) is not None]
            if not values or any(isinstance(value, (str, dict, list, tuple)) for value in values):
                field_type = pa.string()
            elif any(isinstance(value, float) for value in values):
                field_type = pa.float64()
            elif all(isinstance(value, bool) for value in values):
                field_type = pa.bool_()
            elif all(isinstance(value, int | bool) for value in values):
                field_type = pa.int64()
            else:
                field_type = pa.string()
            fields.append(pa.field(name, field_type))
        return pa.schema(fields)

    def open_writer_with_initial_rows(rows: list[dict[str, Any]]) -> None:
        nonlocal writer, active_schema, row_count
        active_schema = initial_schema_for_rows(rows)
        writer = pq.ParquetWriter(path, active_schema)
        start = 0
        while start < len(rows):
            chunk = rows[start : start + normalized_batch_size]
            table = pa.Table.from_pylist(
                coerce_rows_to_schema(chunk, active_schema),
                schema=active_schema,
            )
            writer.write_table(table)
            row_count += len(chunk)
            start += normalized_batch_size

    try:
        for record in records:
            batch.append(normalize(record))
            if schema is not None:
                if len(batch) >= normalized_batch_size:
                    flush(batch)
                    batch = []
            elif writer is None:
                if len(batch) < initial_schema_scan_limit:
                    continue
                open_writer_with_initial_rows(batch)
                batch = []
            elif len(batch) >= normalized_batch_size:
                flush(batch)
                batch = []
        if writer is None:
            if batch:
                open_writer_with_initial_rows(batch)
            else:
                empty_schema = schema or (
                    pa.schema([(column, pa.string()) for column in column_names])
                    if column_names
                    else pa.schema([])
                )
                writer = pq.ParquetWriter(path, empty_schema)
        elif batch:
            flush(batch)
    finally:
        if writer is not None:
            writer.close()
    return row_count


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
