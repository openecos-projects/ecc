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


def projection_lines(csv_dir: Path, design: str, *, spec: CsvExportSpec | None = None) -> list[str]:
    csv_dir = Path(csv_dir)
    if spec is None:
        spec_path = csv_dir / "export_spec.yml"
        if spec_path.is_file():
            spec = load_csv_spec(str(spec_path))
    lines = [f"design: {design}", "section: metrics"]
    metrics_rows = {
        (row.get("metric_name") or ""): row
        for row in read_csv_rows(csv_dir / "qor_metrics.csv")
        if row.get("metric_name")
    }
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
    checklist_rows = {
        (row.get("id") or ""): row
        for row in read_csv_rows(csv_dir / "checklist.csv")
        if row.get("id")
    }
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
