"""Collectors for the five mandatory product CSV views.

Each collector returns a list of dictionaries plus the CSV field order. They
only read files below a finished workspace; no collection function imports or
mutates product code.
"""

from pathlib import Path
from typing import Any

from signoff_csv.common import (
    artifact_row,
    flow_ledger,
    gate_state,
    metric_number,
    metric_records,
    read_json,
    relative_to_workspace,
    step_directory,
    step_tool,
)


STA_METRIC_UNITS = {
    "sta_setup_wns": "ns",
    "sta_setup_tns": "ns",
    "sta_setup_violation_count": "count",
    "sta_hold_wns": "ns",
    "sta_hold_tns": "ns",
    "sta_hold_violation_count": "count",
    "sta_frequency_mhz": "MHz",
    "sta_corner_count": "count",
    "sta_expected_corner_count": "count",
    "sta_missing_corner_count": "count",
}

AREA_SOURCES = {
    "Synthesis": ("Synthesis_yosys", ("synthesis_cell_area",)),
    "postFloorplan": ("postFloorplan_ecc", ("die_area", "core_area", "core_utilization")),
    "Harden": ("Harden_ecc", ("die_area", "core_area", "core_utilization")),
}

AREA_UNITS = {
    "synthesis_cell_area": "um^2",
    "die_area": "um^2",
    "core_area": "um^2",
    "core_utilization": "ratio",
}

HARDEN_METRIC_UNITS = {
    "harden_artifact_missing_count": "count",
    "die_area": "um^2",
    "core_area": "um^2",
    "core_utilization": "ratio",
}


def _metric_rows(workspace: Path, directory: str, wanted: dict[str, str], kind: str) -> list[dict[str, Any]]:
    records = metric_records(workspace, directory)
    rows = []
    for metric_id, unit in wanted.items():
        record = records.get(metric_id)
        source = workspace / directory / "analysis" / "qor_metrics.json"
        rows.append(
            {
                "kind": kind,
                "corner": "",
                "rc_corner": "",
                "metric": metric_id,
                "value": metric_number(record),
                "unit": unit,
                "source": relative_to_workspace(workspace, source),
                "present": str(metric_id in records).lower(),
            }
        )
    return rows


def collect_sta(workspace: Path, flow: dict[str, Any]) -> list[dict[str, Any]]:
    directory = step_directory(flow, "sta")
    rows = _metric_rows(workspace, directory, STA_METRIC_UNITS, "qor_metrics")

    feature_root = workspace / directory / "feature"
    for summary_path in sorted(feature_root.glob("*/*/qor_summary.json")):
        parts = summary_path.parts
        if len(parts) < 2:
            continue
        corner = parts[-3]
        rc_corner = parts[-2]
        data = read_json(summary_path)
        if not isinstance(data, dict):
            continue
        summary = data.get("summary")
        if not isinstance(summary, dict):
            continue
        setup = summary.get("setup")
        hold = summary.get("hold")
        setup = setup if isinstance(setup, dict) else {}
        hold = hold if isinstance(hold, dict) else {}
        for suffix, payload in (("setup", setup), ("hold", hold)):
            for field, unit in (
                ("wns", "ns"),
                ("tns", "ns"),
                ("nvp", "count"),
            ):
                rows.append(
                    {
                        "kind": "corner_summary",
                        "corner": corner,
                        "rc_corner": rc_corner,
                        "metric": f"{suffix}_{field}",
                        "value": str(payload.get(field, "")),
                        "unit": unit,
                        "source": relative_to_workspace(workspace, summary_path),
                        "present": "true",
                    }
                )
        if "frequency_mhz" in setup:
            rows.append(
                {
                    "kind": "corner_summary",
                    "corner": corner,
                    "rc_corner": rc_corner,
                    "metric": "setup_frequency_mhz",
                    "value": str(setup.get("frequency_mhz", "")),
                    "unit": "MHz",
                    "source": relative_to_workspace(workspace, summary_path),
                    "present": "true",
                }
            )
    return rows


def collect_drc(workspace: Path, flow: dict[str, Any]) -> list[dict[str, Any]]:
    directory = step_directory(flow, "drc")
    records = metric_records(workspace, directory)
    metric_id = "drc_count"
    record = records.get(metric_id)
    source = workspace / directory / "analysis" / "qor_metrics.json"
    return [
        {
            "kind": "metric",
            "metric": metric_id,
            "value": metric_number(record),
            "unit": "count",
            "gate": "qor.drc.clean",
            "gate_state": gate_state(workspace, directory, "qor.drc.clean"),
            "source": relative_to_workspace(workspace, source),
            "present": str(metric_id in records).lower(),
        }
    ]


def _postroute_result_paths(workspace: Path, flow: dict[str, Any]) -> list[Path]:
    preferred = step_directory(flow, "postRouteLec")
    candidates = [
        path
        for path in workspace.glob("postRouteLec_*_*/output/*_postRouteLec_result.json")
        if path.is_file()
    ]
    preferred_candidates = [path for path in candidates if preferred in path.parts]
    if preferred_candidates:
        return [preferred_candidates[0]]
    return candidates[:1]


def collect_lec(workspace: Path, flow: dict[str, Any]) -> list[dict[str, Any]]:
    paths = _postroute_result_paths(workspace, flow)
    if not paths:
        return [
            {
                "status": "missing",
                "golden_verilog": "",
                "golden_sha256": "",
                "golden_size_bytes": "",
                "gate_verilog": "",
                "gate_sha256": "",
                "gate_size_bytes": "",
                "source": "",
                "present": "false",
            }
        ]

    path = paths[0]
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    return [
        {
            "status": str(data.get("status", "incomplete")),
            "golden_verilog": str(data.get("golden_verilog", "")),
            "golden_sha256": str(data.get("golden_sha256", "")),
            "golden_size_bytes": str(data.get("golden_size_bytes", "")),
            "gate_verilog": str(data.get("gate_verilog", "")),
            "gate_sha256": str(data.get("gate_sha256", "")),
            "gate_size_bytes": str(data.get("gate_size_bytes", "")),
            "source": relative_to_workspace(workspace, path),
            "present": "true",
        }
    ]


def collect_harden(workspace: Path, flow: dict[str, Any]) -> list[dict[str, Any]]:
    directory = step_directory(flow, "Harden")
    design = str(flow.get("design") or workspace.name)
    rows = _metric_rows(workspace, directory, HARDEN_METRIC_UNITS, "metric")

    for artifact_name in ("gds", "lef", "lib"):
        artifact_path = workspace / directory / "output" / f"{design}_Harden.{artifact_name}"
        rows.append(artifact_row(workspace, artifact_path, artifact_name))
    return rows


def collect_area(workspace: Path, flow: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for step, (directory, metric_ids) in AREA_SOURCES.items():
        records = metric_records(workspace, directory)
        source = workspace / directory / "analysis" / "qor_metrics.json"
        for metric_id in metric_ids:
            rows.append(
                {
                    "step": step,
                    "metric": metric_id,
                    "value": metric_number(records.get(metric_id)),
                    "unit": AREA_UNITS[metric_id],
                    "source": relative_to_workspace(workspace, source),
                    "present": str(metric_id in records).lower(),
                }
            )
    return rows
