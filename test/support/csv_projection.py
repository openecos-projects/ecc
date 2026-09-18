"""Stable text projection of CSV tables for FileCheck."""

from __future__ import annotations

import csv
from pathlib import Path


def read_csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def projection_lines(csv_dir: Path, design: str) -> list[str]:
    """Emit one stable line per metric/checklist id for FileCheck."""
    lines = [f"design: {design}", "section: metrics"]
    seen_metrics: set[str] = set()
    for row in read_csv_rows(csv_dir / "qor_metrics.csv"):
        name = row.get("metric_name") or ""
        if not name or name in seen_metrics:
            continue
        seen_metrics.add(name)
        lines.append(
            "metric {name} value={value} present={present} reference={reference}".format(
                name=name,
                value=row.get("value", ""),
                present=row.get("present", "true"),
                reference=row.get("reference", ""),
            )
        )
    if not seen_metrics:
        lines.append("metrics: empty")

    lines.append("section: checklist")
    seen_checklist: set[str] = set()
    for row in read_csv_rows(csv_dir / "checklist.csv"):
        item_id = row.get("id") or ""
        if not item_id or item_id in seen_checklist:
            continue
        seen_checklist.add(item_id)
        lines.append(
            "checklist {item_id} state={state} present={present} blocked={blocked}".format(
                item_id=item_id,
                state=row.get("state", ""),
                present=row.get("present", "true"),
                blocked=row.get("blocked", ""),
            )
        )
    if not seen_checklist:
        lines.append("checklist: empty")
    return lines


def write_projection(csv_dir: Path, design: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(projection_lines(csv_dir, design)) + "\n"
    destination.write_text(text, encoding="utf-8")
    return destination
