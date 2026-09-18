"""YAML profile for CI/test CSV export (not an ``ecc`` CLI surface).

Reference gates and include lists live in the profile so they can change
without code edits. When an include list is set, the CSV always emits one
contract row per requested id (``present=false`` if the workspace has no
matching data).
"""

import dataclasses
import os
from pathlib import Path

import yaml

TABLE_KEYS = (
    "qor_summary",
    "qor_metrics",
    "checklist",
    "flow_steps",
)

TABLE_KEY_TO_FILE = {key: f"{key}.csv" for key in TABLE_KEYS}


@dataclasses.dataclass(frozen=True)
class MetricSpec:
    id: str
    reference: object | None = None


@dataclasses.dataclass(frozen=True)
class ChecklistItemSpec:
    id: str


@dataclasses.dataclass(frozen=True)
class CsvExportSpec:
    """Parsed ``version: 1`` CSV export profile."""

    version: int
    tables: tuple[str, ...] | None
    metrics: tuple[MetricSpec, ...] | None
    checklist: tuple[ChecklistItemSpec, ...] | None
    flow_steps: tuple[str, ...] | None
    source_path: str | None = None


class CsvSpecError(ValueError):
    """Invalid or unreadable CSV export profile."""


def load_csv_spec(path: str) -> CsvExportSpec:
    """Load and validate a CSV export profile from ``path``."""
    resolved = os.path.abspath(os.path.expanduser(path))
    try:
        with open(resolved, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise CsvSpecError(f"cannot read csv spec: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CsvSpecError(f"invalid yaml in csv spec: {exc}") from exc
    return parse_csv_spec(payload, source_path=resolved)


def parse_csv_spec(payload, *, source_path: str | None = None) -> CsvExportSpec:
    if not isinstance(payload, dict):
        raise CsvSpecError("csv spec root must be a mapping")
    version = payload.get("version", 1)
    if version != 1:
        raise CsvSpecError(f"unsupported csv spec version: {version!r}")

    tables = _optional_string_list(payload.get("tables"), field="tables")
    if tables is not None:
        unknown = [name for name in tables if name not in TABLE_KEY_TO_FILE]
        if unknown:
            raise CsvSpecError(
                f"unknown table(s): {', '.join(unknown)}; expected one of {', '.join(TABLE_KEYS)}"
            )

    metrics = _parse_metrics(payload.get("metrics"))
    checklist = _parse_checklist(payload.get("checklist"))
    flow_steps = _optional_string_list(payload.get("flow_steps"), field="flow_steps")

    return CsvExportSpec(
        version=1,
        tables=tables,
        metrics=metrics,
        checklist=checklist,
        flow_steps=flow_steps,
        source_path=source_path,
    )


def default_profile_path() -> Path:
    """Default CI/test profile with mutable reference gates."""
    return Path(__file__).resolve().parent / "csv_profiles" / "signoff.yml"


def _optional_string_list(value, *, field: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CsvSpecError(f"{field} must be a non-empty list when set")
    items = []
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
    items = []
    seen = set()
    for entry in value:
        if isinstance(entry, str):
            metric_id = entry.strip()
            reference = None
        elif isinstance(entry, dict):
            raw_id = entry.get("id") or entry.get("name")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise CsvSpecError("metrics[].id must be a non-empty string")
            metric_id = raw_id.strip()
            reference = entry.get("reference", entry.get("ref"))
        else:
            raise CsvSpecError("metrics entries must be strings or mappings")
        if metric_id in seen:
            raise CsvSpecError(f"duplicate metric id: {metric_id}")
        seen.add(metric_id)
        items.append(MetricSpec(id=metric_id, reference=reference))
    return tuple(items)


def _parse_checklist(value) -> tuple[ChecklistItemSpec, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CsvSpecError("checklist must be a non-empty list when set")
    items = []
    seen = set()
    for entry in value:
        if isinstance(entry, str):
            item_id = entry.strip()
        elif isinstance(entry, dict):
            raw_id = entry.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise CsvSpecError("checklist[].id must be a non-empty string")
            item_id = raw_id.strip()
        else:
            raise CsvSpecError("checklist entries must be strings or mappings")
        if item_id in seen:
            raise CsvSpecError(f"duplicate checklist id: {item_id}")
        seen.add(item_id)
        items.append(ChecklistItemSpec(id=item_id))
    return tuple(items)
