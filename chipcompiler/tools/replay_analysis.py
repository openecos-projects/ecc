"""Freeze spatial analysis results in the producing Replay attempt.

Coordinates are native DBU. Reports without geometry retain exact instance/net
names for resolution against this attempt's final scene; no guessed positions.
"""

import csv
import hashlib
import json
import logging
import math
from collections import defaultdict
from pathlib import Path

from chipcompiler.tools.replay_analysis_compact import compact_analysis
from chipcompiler.tools.replay_harden import lef_views, liberty_views
from chipcompiler.tools.replay_reports import deliverables, formal, rcx
from chipcompiler.tools.replay_storage import atomic_json, within

logger = logging.getLogger(__name__)


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite analysis value")
    return number


def _box(value):
    if len(value) != 4 or any(type(x) is not int for x in value):
        raise ValueError("Analysis rectangles must be integer DBU")
    if value[0] > value[2] or value[1] > value[3]:
        raise ValueError("Inverted analysis rectangle")
    return value


def _view(label, kind, items, *, unit="", summary=None):
    return {"label": label, "kind": kind, "unit": unit, "items": items, "summary": summary or {}}


def violations(path, kind):
    document = json.loads(path.read_text())
    rows = document if kind == "drc" else document.get("violations", [])
    groups = defaultdict(list)
    for row in rows:
        details = {
            key: value
            for key, value in row.items()
            if key not in {"type", "shape", "shapes", "location", "net", "instance"}
        }
        item = {"label": str(row.get("type", kind)), "details": details, "bboxes": []}
        if kind == "drc":
            item["bboxes"] = [_box(row["shape"][:4])]
            item["nets"] = row.get("net") or []
        elif kind == "lvs":
            item["bboxes"] = [_box(shape["rect"]) for shape in row.get("shapes", [])]
            item["instances"] = [row["instance"]] if row.get("instance") else []
            item["nets"] = [row["net"]] if row.get("net") else []
        else:
            location = row.get("location")
            if location:
                item["bboxes"] = [_box([location[k] for k in ("lx", "ly", "hx", "hy")])]
            item["instances"] = [row["instance"]] if row.get("instance") else []
            item["nets"] = [row["net"]] if row.get("net") else []
            item["value"] = _number(row["ratio"])
        groups[item["label"]].append(item)
    summary = {"reported_violations": len(rows)}
    if kind == "antenna":
        summary.update(document.get("antenna_check", {}))
    return [
        _view(f"{kind.upper()} · {label}", kind, items, summary=summary)
        for label, items in sorted(groups.items())
    ] or [_view(kind.upper(), kind, [], summary=summary)]


def timing(path):
    document = json.loads(path.read_text())
    groups = defaultdict(list)
    for row in document.get("paths", []):
        item = {
            "label": f"{row.get('start_point', '?')} → {row.get('end_point', '?')}",
            "value": _number(row["slack_ns"]),
            "details": {
                **{
                    key: row[key]
                    for key in (
                        "analysis_type",
                        "start_point",
                        "end_point",
                        "slack_ns",
                        "arrival_ns",
                        "required_ns",
                    )
                    if key in row
                },
                "stages": [
                    {
                        key: stage[key]
                        for key in ("instance", "pin", "kind", "incremental_delay_ns")
                        if key in stage
                    }
                    for stage in row.get("stages", [])
                ],
            },
        }
        groups[row.get("analysis_type", "timing")].append(item)
    corner = document.get("corner", path.parent.name)
    return [
        _view(
            f"{corner} · {kind}",
            "timing",
            items,
            unit="ns",
            summary={"reported_paths": len(items), "path_limit": document.get("path_limit")},
        )
        for kind, items in sorted(groups.items())
    ]


def power(path):
    with path.open() as stream:
        reader = csv.DictReader(
            (line for line in stream if not line.startswith("#")), delimiter="\t"
        )
        columns = reader.fieldnames or []
        rows = list(reader)
    metadata_path = path.with_name("metadata.json")
    metadata = (
        json.loads(metadata_path.read_text()) if "lx" in columns and metadata_path.is_file() else {}
    )
    views = []
    # Coordinates are already in the step's geometry. Validate a spatial report
    # if supplied, but keep only names/values; the native viewer orders the sweep.
    if "lx" in columns:
        for row in rows:
            _box([int(row[key]) for key in ("lx", "ly", "hx", "hy")])
    for component in ("total", "internal", "switching", "leakage"):
        column = f"{component}_power_w"
        if column not in columns:
            continue

        items = [
            {
                "label": row["instance_name"],
                "value": _number(row[column]),
            }
            for row in rows
        ]
        views.append(
            _view(
                f"Instance {component} power",
                "power",
                items,
                unit="W",
                summary={
                    "reported_instances": len(items),
                    "reported_sum_w": sum(item["value"] for item in items),
                    "quantity": "Power per instance; not power per area",
                    "component": component,
                    "spatial_coverage": metadata,
                },
            )
        )
    return views


def inventory(path):
    document = json.loads(path.read_text())
    # RC and export summaries are result browsing, not fabricated geometric motion.
    return [_view(path.stem, "report", [], summary=document)]


def collect_analysis(step, directory: Path, started_unix_ns: int) -> dict:
    from chipcompiler.tools.geometry_display import metadata

    manifest = getattr(getattr(step, "output", None), "geometry_manifest", None)
    if manifest and Path(manifest).is_file():
        manifest = Path(manifest)
        native_views = 0
        for line in manifest.read_text().splitlines():
            if not line.startswith("display."):
                continue
            asset = within(manifest.parent, manifest.parent / line.split("=", 1)[1])
            info = metadata(asset)
            kind = info["kind"]
            if kind in {"power", "timing", "lvs", "antenna", "em", "rcx"} or (
                kind == "ir" and not info.get("layer")
            ):
                native_views += 1
        if step.name == "drc":
            native_views += int(
                any(
                    line.startswith("drc=") and line.endswith(".gdisplay")
                    for line in manifest.read_text().splitlines()
                )
            )
        if native_views:
            relative = "subflows/analysis/overlays/index.json"
            atomic_json(
                directory / relative,
                {
                    "schema": "ecos.replay.analysis.v2",
                    "views": [],
                    "unavailable": [],
                    "geometry_display": True,
                },
            )
            return {"analysis": relative, "analysis_view_count": native_views}
    patterns = {
        "drc": [("data/drc/violation_map.json", lambda p: violations(p, "drc"))],
        "lvs": [("data/lvs/lvs_reporter/ilvs.json", lambda p: violations(p, "lvs"))],
        "antennaCheck": [("feature/*.step.json", lambda p: violations(p, "antenna"))],
        "sta": [("feature/**/timing_paths.json", timing)],
        "powerAnalysis": [
            ("output/geometry/power/instance_power_geometry.tsv", power),
            ("data/pw/power_reporter/instance_power.tsv", power),
        ],
        "RCX": [("output/*.spef", rcx)],
        "lec": [("output/*_result.json", formal)],
        "postRouteLec": [("output/*_result.json", formal)],
        "Harden": [
            ("output/*.lef", lambda p: lef_views(p, Path(step.input.def_))),
            ("output/*.lib", liberty_views),
        ],
        "emir": [("emir.json", lambda p: json.loads(p.read_text())["views"])],
    }
    if step.name not in patterns:
        return {}
    root = directory / "capture/analysis" if step.name == "emir" else Path(step.directory)
    relative = "subflows/analysis/overlays"
    destination = directory / relative
    views, unavailable = [], []
    if step.name == "Harden":
        views.append(deliverables(step, started_unix_ns))
    for pattern, parse in patterns[step.name]:
        if (
            step.name == "powerAnalysis"
            and pattern == "data/pw/power_reporter/instance_power.tsv"
            and views
        ):
            continue
        paths = sorted(root.glob(pattern))
        fresh = [p for p in paths if p.is_file() and p.stat().st_mtime_ns >= started_unix_ns]
        if not fresh:
            unavailable.append(f"No current report: {pattern}")
        for path in fresh:
            try:
                source = within(root, path)
                parsed = parse(source)
                # The parsed display payload is self-contained. Provenance does
                # not require another full copy of SPEF/TSV/JSON/LEF/LIB reports.
                with source.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                for view in parsed:
                    view["source"] = {
                        "report": source.relative_to(root).as_posix(),
                        "sha256": digest,
                    }
                    view["basis"] = "final"
                views.extend(parsed)
            except (OSError, ValueError, KeyError, TypeError) as error:
                unavailable.append(f"{path.relative_to(root)}: {error}")
                logger.warning("Replay analysis unavailable: %s", unavailable[-1])
    if step.name in {"lec", "postRouteLec"}:
        for path in sorted((directory / "capture").glob("kepler-*.json")):
            event = json.loads(path.read_text())
            if event.get("state_domain") == "analysis_complete":
                views.append(
                    {
                        "label": "Formal coverage",
                        "kind": "formal",
                        "basis": "final",
                        "items": [],
                        "summary": event.get("metrics", {}),
                    }
                )
            elif event.get("phase") in {
                "cec_difference_cone",
                "sec_difference_cone",
                "sec_counterexample",
            }:
                metrics = event.get("metrics", {})
                views.append(
                    {
                        "label": event["phase"].replace("_", " "),
                        "kind": "formal",
                        "basis": "final",
                        "items": [
                            {"label": key.replace("_", " "), "details": value}
                            for key, value in metrics.items()
                        ],
                        "summary": {
                            "source_phase": event["phase"],
                            "coordinate_space": "logical",
                            "note": "Engine witness/cone evidence; no inferred physical mapping",
                        },
                    }
                )
    payload = compact_analysis(views, unavailable)
    atomic_json(destination / "index.json", payload)
    return {"analysis": f"{relative}/index.json", "analysis_view_count": len(views)}
