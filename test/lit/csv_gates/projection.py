"""FileCheck projection text from exported CSV + spec gates."""

from __future__ import annotations

import csv
from pathlib import Path

from csv_gates.compare import evaluate_checklist_gate, evaluate_metric_gate
from csv_gates.spec import CsvExportSpec, load_csv_spec


def read_csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def projection_lines(
    csv_dir: Path | None,
    design: str,
    *,
    spec: CsvExportSpec | None = None,
    metrics_rows: dict[str, dict] | None = None,
    checklist_rows: dict[str, dict] | None = None,
) -> list[str]:
    """Build FileCheck text from CSV files and/or in-memory rows."""
    csv_dir = Path(csv_dir) if csv_dir is not None else None
    if spec is None and csv_dir is not None:
        spec_path = csv_dir / "export_spec.yml"
        if spec_path.is_file():
            spec = load_csv_spec(str(spec_path))
    if metrics_rows is None:
        metrics_rows = {
            (row.get("metric_name") or ""): row
            for row in (read_csv_rows(csv_dir / "qor_metrics.csv") if csv_dir else [])
            if row.get("metric_name")
        }
    if checklist_rows is None:
        checklist_rows = {
            (row.get("id") or ""): row
            for row in (read_csv_rows(csv_dir / "checklist.csv") if csv_dir else [])
            if row.get("id")
        }
    lines = [f"design: {design}", "section: metrics"]
    metric_order = (
        [item.id for item in spec.metrics] if spec and spec.metrics else list(metrics_rows)
    )
    seen: set[str] = set()
    for name in metric_order:
        if not name or name in seen:
            continue
        seen.add(name)
        row = metrics_rows.get(name) or {"value": "", "present": "false", "reference": ""}
        lines.append(
            f"metric {name} value={row.get('value', '')} "
            f"present={row.get('present', 'true')} reference={row.get('reference', '')}"
        )
    if not seen:
        lines.append("metrics: empty")
    lines.append("section: checklist")
    checklist_order = (
        [item.id for item in spec.checklist] if spec and spec.checklist else list(checklist_rows)
    )
    seen = set()
    for item_id in checklist_order:
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        row = checklist_rows.get(item_id) or {"state": "", "present": "false", "blocked": ""}
        lines.append(
            f"checklist {item_id} state={row.get('state', '')} "
            f"present={row.get('present', 'true')} blocked={row.get('blocked', '')}"
        )
    if not seen:
        lines.append("checklist: empty")
    lines.append(f"readiness: {_readiness_from_checklist_rows(list(checklist_rows.values()))}")
    lines.append("section: gates")
    if spec and spec.metrics:
        for item in spec.metrics:
            row = metrics_rows.get(item.id) or {"value": "", "present": "false"}
            status = evaluate_metric_gate(row, item)
            ref = "" if item.reference is None else item.reference
            lines.append(
                f"gate metric {item.id} status={status} op={item.op} "
                f"ref={ref} value={row.get('value', '')}"
            )
    if spec and spec.checklist:
        for item in spec.checklist:
            row = checklist_rows.get(item.id) or {"state": "", "present": "false", "blocked": ""}
            status = evaluate_checklist_gate(row, item)
            lines.append(
                f"gate checklist {item.id} status={status} "
                f"state={row.get('state', '')} blocked={row.get('blocked', '')}"
            )
    return lines


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _readiness_from_checklist_rows(rows: list[dict]) -> str:
    """Map checklist CSV rows to milestone readiness (fixture-friendly, no PDK)."""
    if not rows:
        return "PASS"
    saw_failed = False
    saw_unavailable = False
    saw_attention = False
    for row in rows:
        state = str(row.get("state") or "").strip().lower()
        # CSV may use fail / failed
        if state == "fail":
            state = "failed"
        present = str(row.get("present") or "true").strip().lower()
        blocked = _truthy(row.get("blocked"))
        if present == "false" or state in {"", "unavailable", "missing"}:
            saw_unavailable = True
        elif blocked and state == "failed":
            saw_failed = True
        elif state == "failed" or state not in {"pass", "passed"}:
            saw_attention = True
    if saw_failed:
        return "ERROR"
    if saw_unavailable:
        return "MISS"
    if saw_attention:
        return "WARN"
    return "PASS"