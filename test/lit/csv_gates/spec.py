"""YAML profile → typed CsvExportSpec."""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

from csv_gates.compare import METRIC_OPS

TABLE_KEYS = ("qor_summary", "qor_metrics", "checklist", "flow_steps")
TABLE_KEY_TO_FILE = {key: f"{key}.csv" for key in TABLE_KEYS}


class CsvSpecError(ValueError):
    """Invalid or unsupported CSV export profile."""


@dataclass(frozen=True)
class MetricSpec:
    id: str
    reference: object | None = None
    op: str = "=="


@dataclass(frozen=True)
class ChecklistItemSpec:
    id: str
    require_state: str | None = "pass"
    require_blocked: bool | None = False


@dataclass(frozen=True)
class CsvExportSpec:
    version: int
    tables: tuple[str, ...] | None
    metrics: tuple[MetricSpec, ...] | None
    checklist: tuple[ChecklistItemSpec, ...] | None
    flow_steps: tuple[str, ...] | None
    source_path: str | None = None


def _optional_string_list(value, *, field: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CsvSpecError(f"{field} must be a non-empty list when set")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise CsvSpecError(f"{field} entries must be non-empty strings")
        items.append(entry.strip())
    return tuple(items)


def _parse_metrics(value) -> tuple[MetricSpec, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CsvSpecError("metrics must be a non-empty list when set")
    items: list[MetricSpec] = []
    seen: set[str] = set()
    for entry in value:
        if isinstance(entry, str):
            metric_id, reference, op = entry.strip(), None, "=="
        elif isinstance(entry, dict):
            raw_id = entry.get("id") or entry.get("name")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise CsvSpecError("metrics[].id must be a non-empty string")
            metric_id = raw_id.strip()
            reference = entry.get("reference", entry.get("ref"))
            raw_op = entry.get("op", "==")
            if not isinstance(raw_op, str) or raw_op not in METRIC_OPS:
                raise CsvSpecError(f"metrics[].op must be one of {', '.join(METRIC_OPS)}")
            op = raw_op
        else:
            raise CsvSpecError("metrics entries must be strings or mappings")
        if metric_id in seen:
            raise CsvSpecError(f"duplicate metric id: {metric_id}")
        seen.add(metric_id)
        items.append(MetricSpec(id=metric_id, reference=reference, op=op))
    return tuple(items)


def _parse_checklist(value) -> tuple[ChecklistItemSpec, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CsvSpecError("checklist must be a non-empty list when set")
    items: list[ChecklistItemSpec] = []
    seen: set[str] = set()
    for entry in value:
        if isinstance(entry, str):
            item_id = entry.strip()
            require_state: str | None = "pass"
            require_blocked: bool | None = False
        elif isinstance(entry, dict):
            raw_id = entry.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise CsvSpecError("checklist[].id must be a non-empty string")
            item_id = raw_id.strip()
            if "require_state" in entry:
                raw_state = entry.get("require_state")
                if raw_state is None:
                    require_state = None
                elif isinstance(raw_state, str) and raw_state.strip():
                    require_state = raw_state.strip()
                else:
                    raise CsvSpecError("checklist[].require_state must be a string or null")
            else:
                require_state = "pass"
            if "require_blocked" in entry:
                raw_blocked = entry.get("require_blocked")
                if raw_blocked is None:
                    require_blocked = None
                elif isinstance(raw_blocked, bool):
                    require_blocked = raw_blocked
                else:
                    raise CsvSpecError("checklist[].require_blocked must be a bool or null")
            else:
                require_blocked = False
        else:
            raise CsvSpecError("checklist entries must be strings or mappings")
        if item_id in seen:
            raise CsvSpecError(f"duplicate checklist id: {item_id}")
        seen.add(item_id)
        items.append(
            ChecklistItemSpec(
                id=item_id, require_state=require_state, require_blocked=require_blocked
            )
        )
    return tuple(items)


def load_csv_spec(path: str) -> CsvExportSpec:
    resolved = os.path.abspath(os.path.expanduser(path))
    try:
        with open(resolved, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise CsvSpecError(f"cannot read csv spec: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CsvSpecError(f"invalid yaml in csv spec: {exc}") from exc
    if not isinstance(payload, dict):
        raise CsvSpecError("csv spec root must be a mapping")
    version = payload.get("version", 1)
    if version != 1:
        raise CsvSpecError(f"unsupported csv spec version: {version!r}")
    tables = _optional_string_list(payload.get("tables"), field="tables")
    if tables is not None:
        unknown = [name for name in tables if name not in TABLE_KEY_TO_FILE]
        if unknown:
            raise CsvSpecError(f"unknown table(s): {', '.join(unknown)}")
    return CsvExportSpec(
        version=1,
        tables=tables,
        metrics=_parse_metrics(payload.get("metrics")),
        checklist=_parse_checklist(payload.get("checklist")),
        flow_steps=_optional_string_list(payload.get("flow_steps"), field="flow_steps"),
        source_path=resolved,
    )
