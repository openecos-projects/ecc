#!/usr/bin/env python

import hashlib
import json
import os
import re
from math import isfinite
from pathlib import Path

from chipcompiler.data import Workspace

CTS_RUNTIME_REPORT_REVISION = "ecc.cts.parameter_runtime_report.v1"
FLOORPLAN_RUNTIME_REPORT_REVISION = "ecc.floorplan.parameter_runtime_report.v2"
_RUNTIME_REPORT_REF = "analysis/parameter_runtime_report.v1.json"


def _source_sha256() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _candidate_patch(workspace_dir: Path, knob_ids: set[str]) -> dict | None:
    path = workspace_dir / "analysis" / "candidate_materialization.v1.json"
    if not path.is_file():
        return None
    try:
        materialization = json.loads(path.read_text(encoding="utf-8"))
        return next(item for item in materialization["patch"] if item.get("knob_id") in knob_ids)
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None


def _write_runtime_report(workspace_dir: Path, report: dict) -> None:
    output_path = workspace_dir / _RUNTIME_REPORT_REF
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(temporary, output_path)


def _write_cts_parameter_runtime_report(
    workspace: Workspace,
    config_path: str | Path,
    *,
    engine_succeeded: bool,
) -> None:
    """Record CTS config effectiveness without claiming unobserved activation."""
    workspace_dir = getattr(workspace, "directory", None)
    if workspace_dir is None:
        return
    workspace_dir = Path(workspace_dir)
    patch = _candidate_patch(workspace_dir, {"cts.max_fanout"})
    if patch is None:
        return
    try:
        value = json.loads(Path(config_path).read_text(encoding="utf-8"))["max_fanout"]
    except (OSError, ValueError, KeyError, TypeError):
        return

    requested = patch.get("value")
    matches_request = type(value) is int and value == requested
    effective = value if engine_succeeded else None
    report = {
        "knob_id": "cts.max_fanout",
        "requested_value": requested,
        "tool": {
            "name": "ECC-CTS",
            "revision": CTS_RUNTIME_REPORT_REVISION,
            "source_sha256": _source_sha256(),
        },
        "application_status": ("applied" if engine_succeeded and matches_request else "unknown"),
        "effective_initial": {"value": effective, "unit": "fanout"},
        "effective_final": {"value": effective, "unit": "fanout"},
        "activation": {"status": "unknown", "consumers": []},
        "consumer_observation": {
            "config_value": value,
            "engine_succeeded": engine_succeeded,
            "activation_evidence_complete": False,
        },
        "transitions": [],
    }
    _write_runtime_report(workspace_dir, report)


def _write_floorplan_parameter_runtime_report(
    workspace: Workspace,
    config_path: str | Path,
    *,
    feature_path: str | Path | None = None,
    report_path: str | Path | None = None,
) -> None:
    """Record the candidate knob consumed by iFP's native die builder."""
    workspace_dir = getattr(workspace, "directory", None)
    if workspace_dir is None:
        return
    workspace_dir = Path(workspace_dir)
    patch = _candidate_patch(workspace_dir, {"floorplan.core_util", "floorplan.aspect_ratio"})
    if patch is None:
        return
    try:
        floorplan = json.loads(Path(config_path).read_text(encoding="utf-8"))
        die_builder = floorplan["die_builder"]
        die_util = die_builder["die_util"]
    except (OSError, ValueError, KeyError, TypeError):
        return

    knob_id = patch["knob_id"]
    field, consumer_id = {
        "floorplan.core_util": ("utilization", "ifp.die_builder.die_utilization"),
        "floorplan.aspect_ratio": ("aspect_ratio", "ifp.die_builder.die_aspect_ratio"),
    }[knob_id]
    value = die_util.get(field)
    requested = patch.get("value")
    mode = die_builder.get("mode")
    matches_request = value == requested
    observation = _floorplan_geometry_observation(feature_path, report_path)
    complete = _floorplan_observation_complete(observation)
    status = (
        "used"
        if complete and mode == "die_util" and value is not None and matches_request
        else "unknown"
    )
    if complete and mode != "die_util" and value is not None and matches_request:
        status = "not_activated"
    evidence = {
        "consumer_id": consumer_id,
        "outcome": "geometry_constructed" if status == "used" else "evaluated",
        "evidence_ref": _RUNTIME_REPORT_REF,
    }
    evidence["evidence_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    report = {
        "knob_id": knob_id,
        "requested_value": requested,
        "tool": {
            "name": "ECC-Floorplan",
            "revision": FLOORPLAN_RUNTIME_REPORT_REVISION,
            "source_sha256": _source_sha256(),
        },
        "application_status": "applied" if complete and matches_request else "unknown",
        "effective_initial": {"value": value, "unit": "ratio"},
        "effective_final": {"value": value, "unit": "ratio"},
        "activation": {
            "status": status,
            "consumers": [evidence] if status in {"used", "not_activated"} else [],
        },
        "transitions": [],
    }
    if observation is not None:
        report["consumer_observation"] = observation
    if feature_path is not None and not complete:
        report["application_status"] = "unknown"
        report["activation"] = {"status": "unknown", "consumers": []}
    _write_runtime_report(workspace_dir, report)


def _floorplan_geometry_observation(
    feature_path: str | Path | None, report_path: str | Path | None
) -> dict | None:
    if not feature_path or not Path(feature_path).is_file():
        return None
    try:
        feature = json.loads(Path(feature_path).read_text(encoding="utf-8"))
        layout = feature["Design Layout"]
        width = layout["core_bounding_width"]
        height = layout["core_bounding_height"]
        area = layout.get("core_area")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    numeric = all(isinstance(item, (int, float)) and isfinite(item) for item in (width, height))
    if not numeric or width <= 0 or height <= 0:
        return None
    ratio = width / height
    rows, sites = _floorplan_report_counts(report_path)
    return {
        "core_geometry": {
            "width": {"value": width, "unit": "um"},
            "height": {"value": height, "unit": "um"},
            "area": {"value": area, "unit": "um^2"},
            "aspect_ratio": {"value": ratio, "unit": "ratio"},
        },
        "rows": {"count": rows, "observed": rows is not None},
        "sites": {"count": sites, "observed": sites is not None},
    }


def _floorplan_observation_complete(observation: dict | None) -> bool:
    if not observation:
        return False
    geometry = observation.get("core_geometry", {})
    return all(
        geometry.get(name, {}).get("value") is not None
        for name in ("width", "height", "area", "aspect_ratio")
    ) and (
        observation.get("rows", {}).get("observed") is True
        and observation.get("sites", {}).get("observed") is True
    )


def _floorplan_report_counts(report_path: str | Path | None) -> tuple[int | None, int | None]:
    if not report_path or not Path(report_path).is_file():
        return None, None
    try:
        text = Path(report_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    values = {}
    for name in ("Site", "Row"):
        match = re.search(rf"Number\s*-\s*{name}[^0-9]*(\d+)", text)
        if match:
            values[name] = int(match.group(1))
    return values.get("Row"), values.get("Site")
