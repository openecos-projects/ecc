"""CSV export for CI/test (not an ``ecc`` CLI surface).

Builds tabular views from workspace QoR inputs, checklist, and flow.json.
"""

import csv
import dataclasses
import io
import os
import shutil
from pathlib import Path

from chipcompiler.utility.file import write_text_atomic
from chipcompiler.utility.json import json_read

TABLE_FILES = (
    "qor_summary.csv",
    "qor_metrics.csv",
    "checklist.csv",
    "flow_steps.csv",
)


@dataclasses.dataclass(frozen=True)
class CsvTable:
    filename: str
    fieldnames: tuple[str, ...]
    rows: tuple[dict, ...]


@dataclasses.dataclass(frozen=True)
class CsvExportBundle:
    design: str
    tables: tuple[CsvTable, ...]
    checklist_available: bool
    overall_score: float | None
    qor_status: str
    checklist_status: str
    spec_path: str | None = None


def render_csv(table: CsvTable) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=table.fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in table.rows:
        writer.writerow({key: _cell(row.get(key)) for key in table.fieldnames})
    return buffer.getvalue()


def build_csv_bundle(workspace, spec=None) -> CsvExportBundle:
    from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs
    from chipcompiler.engine.qor_report import build_qor_report
    from chipcompiler.engine.signoff.report_checklist import build_checklist_report

    qor = build_qor_report(workspace)
    inputs = load_workspace_qor_inputs(workspace)
    checklist = build_checklist_report(workspace)
    design = qor.design or inputs.design or _design_name(workspace)
    status = qor.scalar_summary.status if qor.scalar_summary is not None else ""

    builders = {
        "qor_summary": lambda: _qor_summary_table(qor, inputs, design),
        "qor_metrics": lambda: _qor_metrics_table(inputs, spec),
        "checklist": lambda: _checklist_table(checklist, spec),
        "flow_steps": lambda: _flow_steps_table(workspace, spec),
    }
    selected = list(builders) if spec is None or spec.tables is None else list(spec.tables)
    unknown = [key for key in selected if key not in builders]
    if unknown:
        raise ValueError(f"unsupported csv table(s): {', '.join(unknown)}")
    tables = tuple(builders[key]() for key in selected)
    return CsvExportBundle(
        design=design,
        tables=tables,
        checklist_available=checklist.available,
        overall_score=qor.overall_score,
        qor_status=status,
        checklist_status=checklist.status if checklist.available else "unavailable",
        spec_path=None if spec is None else spec.source_path,
    )


def write_csv_bundle(bundle: CsvExportBundle, destination_dir: str) -> list[dict]:
    os.makedirs(destination_dir, exist_ok=True)
    written = []
    for table in bundle.tables:
        path = os.path.join(destination_dir, table.filename)
        write_text_atomic(path, render_csv(table))
        written.append({"file": table.filename, "rows": len(table.rows), "path": path})

    if bundle.spec_path and os.path.isfile(bundle.spec_path):
        dest = os.path.join(destination_dir, "export_spec.yml")
        shutil.copy2(bundle.spec_path, dest)
        written.append({"file": "export_spec.yml", "rows": 0, "path": dest})
    return written


def _qor_summary_table(qor, inputs, design: str) -> CsvTable:
    summary = qor.scalar_summary
    return CsvTable(
        filename="qor_summary.csv",
        fieldnames=(
            "design",
            "overall_score",
            "status",
            "profile",
            "analyzed_steps",
        ),
        rows=(
            {
                "design": design,
                "overall_score": qor.overall_score,
                "status": summary.status if summary is not None else "",
                "profile": summary.profile if summary is not None else inputs.profile,
                "analyzed_steps": ";".join(inputs.analyzed_steps),
            },
        ),
    )


def _qor_metrics_table(inputs, spec=None) -> CsvTable:
    base_fields = (
        "step",
        "metric_name",
        "value",
        "unit",
        "scope",
        "corner",
        "project_role",
    )
    metrics_spec = None if spec is None else spec.metrics
    if metrics_spec is None:
        rows = tuple(_metric_row(record) for record in inputs.metrics.values())
        return CsvTable(filename="qor_metrics.csv", fieldnames=base_fields, rows=rows)

    rows = []
    for item in metrics_spec:
        record = inputs.metrics.get(item.id)
        if record is None:
            rows.append(
                {
                    "step": "",
                    "metric_name": item.id,
                    "value": "",
                    "unit": "",
                    "scope": "",
                    "corner": "",
                    "project_role": "",
                    "reference": item.reference,
                    "present": False,
                }
            )
        else:
            row = _metric_row(record)
            row["reference"] = item.reference
            row["present"] = True
            rows.append(row)
    return CsvTable(
        filename="qor_metrics.csv",
        fieldnames=base_fields + ("reference", "present"),
        rows=tuple(rows),
    )


def _metric_row(record) -> dict:
    return {
        "step": record.step,
        "metric_name": record.metric_id,
        "value": record.value,
        "unit": record.unit,
        "scope": record.scope or "",
        "corner": record.corner or "",
        "project_role": record.project_role,
    }


def _checklist_table(checklist, spec=None) -> CsvTable:
    base_fields = (
        "id",
        "step",
        "category",
        "title",
        "state",
        "policy",
        "blocked",
        "summary",
        "evidence",
    )
    checklist_spec = None if spec is None else spec.checklist
    if checklist_spec is None:
        return CsvTable(
            filename="checklist.csv",
            fieldnames=base_fields,
            rows=tuple(_checklist_row(item) for item in checklist.items),
        )

    by_id = {item.id: item for item in checklist.items}
    rows = []
    for wanted in checklist_spec:
        item = by_id.get(wanted.id)
        if item is None:
            rows.append(
                {
                    "id": wanted.id,
                    "step": "",
                    "category": "",
                    "title": "",
                    "state": "",
                    "policy": "",
                    "blocked": "",
                    "summary": "",
                    "evidence": "",
                    "present": False,
                }
            )
        else:
            row = _checklist_row(item)
            row["present"] = True
            rows.append(row)
    return CsvTable(
        filename="checklist.csv",
        fieldnames=base_fields + ("present",),
        rows=tuple(rows),
    )


def _checklist_row(item) -> dict:
    return {
        "id": item.id,
        "step": item.step,
        "category": item.category,
        "title": item.title,
        "state": item.state,
        "policy": item.policy,
        "blocked": item.blocked,
        "summary": item.summary,
        "evidence": ";".join(item.evidence),
    }


def _flow_steps_table(workspace, spec=None) -> CsvTable:
    workspace_root = Path(workspace.directory or "")
    flow = json_read(workspace_root / "home" / "flow.json")
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    raw_rows = []
    for step in steps:
        if not isinstance(step, dict) or not step.get("name"):
            continue
        raw_rows.append(
            {
                "name": step.get("name"),
                "tool": step.get("tool", ""),
                "state": step.get("state", ""),
                "runtime": step.get("runtime", ""),
                "peak_memory_mb": step.get("peak memory (mb)", ""),
            }
        )

    allow = None if spec is None else spec.flow_steps
    base_fields = ("name", "tool", "state", "runtime", "peak_memory_mb")
    if allow is None:
        return CsvTable(filename="flow_steps.csv", fieldnames=base_fields, rows=tuple(raw_rows))

    by_name = {row["name"]: row for row in raw_rows}
    by_folded = {str(row["name"]).casefold(): row for row in raw_rows}
    rows = []
    for name in allow:
        row = by_name.get(name) or by_folded.get(name.casefold())
        if row is None:
            rows.append(
                {
                    "name": name,
                    "tool": "",
                    "state": "",
                    "runtime": "",
                    "peak_memory_mb": "",
                    "present": False,
                }
            )
        else:
            rows.append({**row, "present": True})
    return CsvTable(
        filename="flow_steps.csv",
        fieldnames=base_fields + ("present",),
        rows=tuple(rows),
    )


def _design_name(workspace) -> str:
    design = getattr(workspace, "design", None)
    name = getattr(design, "name", None) if design is not None else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return Path(workspace.directory or ".").name


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
