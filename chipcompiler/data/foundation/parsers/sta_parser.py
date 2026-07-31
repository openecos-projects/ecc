from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

CRITICALITY_THRESHOLD = 0.8


def parse_sta_artifacts(stage_dir: Path) -> dict[str, Any]:
    """Parse ECC STA JSON and wire path artifacts into timing-path schema records."""
    rpt_path = stage_dir / "data" / "sta" / "gcd.rpt.json"
    rpt = _read_json(rpt_path)
    summaries = rpt.get("summary", []) if isinstance(rpt.get("summary"), list) else []
    details = rpt.get("detail", []) if isinstance(rpt.get("detail"), list) else []
    slack_rows = rpt.get("slack", []) if isinstance(rpt.get("slack"), list) else []
    wire_paths = sorted((stage_dir / "data" / "sta" / "wire_paths").glob("*.json"))
    slack_summaries = _stage_slack_summaries(slack_rows)
    slack_ranges = _slack_ranges_by_analysis_context(summaries, details)
    records: list[dict[str, Any]] = []
    for idx, item in enumerate(summaries):
        if not isinstance(item, dict):
            continue
        detail = details[idx] if idx < len(details) and isinstance(details[idx], dict) else {}
        wire_path = wire_paths[idx] if idx < len(wire_paths) else None
        wire = _parse_wire_path(wire_path)
        path_points = _path_points(detail.get("detail")) or _points_from_wire_nodes(wire["nodes"])
        endpoint_raw = str(item.get("endpoint") or detail.get("end_point") or "")
        start_raw = str(
            detail.get("start_point") or (path_points[0]["raw_name"] if path_points else "")
        )
        _assign_point_roles(path_points, start_raw, endpoint_raw)
        wire_nodes = _match_wire_nodes(wire["nodes"], path_points)
        timing_edges = _timing_edges(path_points)
        slack = _to_float(
            item.get("slack") if item.get("slack") is not None else detail.get("slack")
        )
        analysis_key = _analysis_context_key(item, detail)
        min_slack, max_slack = slack_ranges.get(analysis_key, (None, None))
        stage_wns, stage_tns = slack_summaries.get(analysis_key, (None, None))
        normalized, normalized_reason = _normalized_criticality(slack, min_slack, max_slack)
        is_worst = slack is not None and min_slack is not None and slack == min_slack
        is_near = is_worst if normalized is None else normalized >= CRITICALITY_THRESHOLD
        null_reason = _empty_null_reason()
        if normalized_reason:
            null_reason["path_timing"]["normalized_criticality"] = normalized_reason
        if wire_path is None:
            null_reason["path_electrical"]["wire_path"] = "missing_wire_path_artifact"
        records.append(
            {
                "identity": {
                    "path_index": idx,
                    "path_key": None,
                    "endpoint_key": _parse_sta_point(endpoint_raw).get("pin_key"),
                    "sequence_hash": _sequence_hash(path_points),
                    "clock_group": item.get("clock_group") or detail.get("clock_field"),
                    "delay_type": item.get("delay_type") or detail.get("type") or "unknown",
                    "record_granularity": "path",
                },
                "analysis_context": {
                    "delay_type": item.get("delay_type") or detail.get("type") or "unknown",
                    "check_type": _check_type(item.get("delay_type") or detail.get("type")),
                    "path_kind": "data",
                    "clock_group": item.get("clock_group") or detail.get("clock_field"),
                    "launch_clock": None,
                    "capture_clock": None,
                    "corner": None,
                    "mode": None,
                },
                "endpoints": {
                    "startpoint": _endpoint_record(start_raw),
                    "endpoint": _endpoint_record(endpoint_raw),
                },
                "path_timing": {
                    "path_delay": _to_float(item.get("path_delay")),
                    "path_required": _to_float(item.get("path_required")),
                    "cppr": _to_float(item.get("cppr")),
                    "slack": slack,
                    "freq": _to_float(item.get("freq")),
                    "rank_in_stage": idx,
                    "is_worst_path": is_worst,
                    "is_violating": bool(slack is not None and slack < 0),
                    "normalized_criticality": normalized,
                    "is_near_critical": is_near,
                    "criticality_threshold": CRITICALITY_THRESHOLD,
                    "stage_wns": stage_wns,
                    "stage_tns": stage_tns,
                },
                "path_electrical": wire["summary"],
                "path_points": path_points,
                "timing_edges": timing_edges,
                "wire_path_nodes": wire_nodes,
                "path_spatial": _empty_path_spatial(),
                "progressive_metadata": {},
                "coverage": _coverage(path_points, timing_edges, wire_nodes),
                "source_refs": {
                    "sta_report": {
                        "path": str(rpt_path),
                        "summary_index": idx,
                        "detail_index": idx if idx < len(details) else None,
                        "slack_index": _slack_index(
                            slack_rows, item.get("clock_group"), item.get("delay_type")
                        ),
                    },
                    "wire_path": {
                        "path": str(wire_path) if wire_path else None,
                        "wire_path_index": idx if wire_path else None,
                    },
                },
                "source": str(rpt_path),
                "wire_path_source": str(wire_path) if wire_path else None,
                "null_reason": null_reason,
            }
        )
    return {
        "available": bool(records or slack_rows),
        "records": records,
        "slack": slack_rows,
        "source": str(rpt_path),
        "wire_path_sources": [str(path) for path in wire_paths],
    }


def _parse_wire_path(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"summary": _empty_electrical(), "nodes": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"summary": _empty_electrical(), "nodes": []}
    nodes: list[dict[str, Any]] = []
    capacitance: list[float] = []
    slew: list[float] = []
    resistance: list[float] = []
    incr: list[float] = []
    if isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if not isinstance(value, dict):
                    continue
                if key.startswith("node_"):
                    cap = _to_float(value.get("Capacitance"))
                    node_slew = _to_float(value.get("slew"))
                    if cap is not None:
                        capacitance.append(cap)
                    if node_slew is not None:
                        slew.append(node_slew)
                    parsed = _parse_sta_point(str(value.get("Point") or ""))
                    nodes.append(
                        {
                            "id": key,
                            "raw_point": value.get("Point"),
                            "matched_point_id": None,
                            **parsed,
                            "capacitance": cap,
                            "slew": node_slew,
                            "transition": value.get("trans_type"),
                        }
                    )
                else:
                    inc = _to_float(value.get("Incr"))
                    res = _to_float(value.get("Resistance") or value.get("R"))
                    if inc is not None:
                        incr.append(inc)
                    if res is not None:
                        resistance.append(res)
    summary = {
        "capacitance_sum": sum(capacitance) if capacitance else None,
        "capacitance_list": capacitance,
        "max_slew": max(slew) if slew else None,
        "slew_list": slew,
        "resistance_sum": sum(resistance) if resistance else None,
        "resistance_list": resistance,
        "incr_delay_sum": sum(incr) if incr else None,
        "incr_delay_list": incr,
    }
    return {"summary": summary, "nodes": nodes}


def _path_points(detail: Any) -> list[dict[str, Any]]:
    if not isinstance(detail, list):
        return []
    points = []
    for idx, item in enumerate(detail):
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "")
        parsed = _parse_sta_point(raw_name)
        points.append(
            {
                "point_id": idx,
                "raw_name": raw_name,
                **parsed,
                "incr_delay": _to_float(item.get("incr_delay")),
                "path_delay": _to_float(item.get("path_delay")),
                "transition": _transition_from_path_delay(item.get("path_delay")),
                "node_role": "internal",
            }
        )
    return points


def _points_from_wire_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    for idx, node in enumerate(nodes):
        raw_name = str(node.get("raw_point") or "")
        points.append(
            {
                "point_id": idx,
                "raw_name": raw_name,
                "instance_name": node.get("instance_name"),
                "instance_key": node.get("instance_key"),
                "pin_name": node.get("pin_name"),
                "pin_key": node.get("pin_key"),
                "master": node.get("master"),
                "parse_status": node.get("parse_status"),
                "incr_delay": None,
                "path_delay": None,
                "transition": node.get("transition"),
                "node_role": "internal",
            }
        )
    return points


def _timing_edges(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for idx, (src, dst) in enumerate(zip(points, points[1:], strict=False)):
        src_key = src.get("instance_key")
        dst_key = dst.get("instance_key")
        edge_kind = "unknown"
        if src.get("node_role") == "clock" or dst.get("node_role") == "clock":
            edge_kind = "clock_arc"
        elif (
            src_key
            and dst_key
            and src_key == dst_key
            and src.get("pin_name") != dst.get("pin_name")
        ):
            edge_kind = "cell_arc"
        elif src.get("pin_key") and dst.get("pin_key"):
            edge_kind = "net_arc"
        edges.append(
            {
                "edge_id": idx,
                "from_point_id": src.get("point_id"),
                "to_point_id": dst.get("point_id"),
                "from_pin_key": src.get("pin_key"),
                "to_pin_key": dst.get("pin_key"),
                "edge_delay": dst.get("incr_delay"),
                "edge_kind": edge_kind,
                "edge_kind_source": "heuristic_point_adjacency",
                "transition": dst.get("transition"),
                "net_name": None,
                "net_key": None,
                "net_degree": None,
                "net_hpwl": None,
                "net_cross_patch": None,
                "net_join_status": "not_applicable" if edge_kind != "net_arc" else "missing",
                "parse_status": "parsed"
                if src.get("pin_key") and dst.get("pin_key")
                else "partial",
            }
        )
    return edges


def _parse_sta_point(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    master = None
    master_match = re.search(r"\(([^()]+)\)\s*$", text)
    if master_match:
        master = master_match.group(1).strip()
        text = text[: master_match.start()].strip()
    instance_name = None
    pin_name = None
    if ":" in text:
        instance_name, pin_name = text.rsplit(":", 1)
    elif "/" in text:
        instance_name, pin_name = text.rsplit("/", 1)
    elif text:
        pin_name = text
    instance_name = (
        instance_name.strip() if isinstance(instance_name, str) and instance_name.strip() else None
    )
    pin_name = pin_name.strip() if isinstance(pin_name, str) and pin_name.strip() else None
    pin_key = None
    if pin_name and instance_name:
        pin_key = f"{instance_name}:{pin_name}"
    elif pin_name:
        pin_key = f"PIN:{pin_name}"
    return {
        "instance_name": instance_name,
        "instance_key": instance_name,
        "pin_name": pin_name,
        "pin_key": pin_key,
        "master": master,
        "parse_status": "parsed" if pin_key else "unparseable",
    }


def _endpoint_record(raw: str) -> dict[str, Any]:
    parsed = _parse_sta_point(raw)
    return {"raw_name": raw, **parsed}


def _assign_point_roles(points: list[dict[str, Any]], start_raw: str, endpoint_raw: str) -> None:
    start_key = _parse_sta_point(start_raw).get("pin_key")
    endpoint_key = _parse_sta_point(endpoint_raw).get("pin_key")
    for idx, point in enumerate(points):
        if point.get("pin_key") == start_key or (start_raw and point.get("raw_name") == start_raw):
            point["node_role"] = "startpoint"
        elif point.get("pin_key") == endpoint_key or (
            endpoint_raw and point.get("raw_name") == endpoint_raw
        ):
            point["node_role"] = "endpoint"
        elif idx == 0 and _is_clock_pin(point.get("pin_name")):
            point["node_role"] = "clock"


def _match_wire_nodes(
    nodes: list[dict[str, Any]], points: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    point_by_key = {
        point.get("pin_key"): point.get("point_id") for point in points if point.get("pin_key")
    }
    out = []
    for node in nodes:
        matched = point_by_key.get(node.get("pin_key"))
        out.append(
            {
                **node,
                "matched_point_id": matched,
                "parse_status": node.get("parse_status")
                or ("parsed" if node.get("pin_key") else "unparseable"),
            }
        )
    return out


def _coverage(
    points: list[dict[str, Any]], edges: list[dict[str, Any]], wire_nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "point_count": len(points),
        "parsed_point_count": sum(1 for point in points if point.get("parse_status") == "parsed"),
        "pin_join_count": 0,
        "edge_count": len(edges),
        "net_join_count": sum(1 for edge in edges if edge.get("net_join_status") == "joined"),
        "wire_node_count": len(wire_nodes),
        "matched_wire_node_count": sum(
            1 for node in wire_nodes if node.get("matched_point_id") is not None
        ),
        "spatial_anchor_count": 0,
        "missing_spatial_anchor_count": len(points),
        "has_complete_endpoint_join": False,
        "has_wire_path": bool(wire_nodes),
        "coverage_notes": [],
    }


def _empty_path_spatial() -> dict[str, Any]:
    return {
        "anchor_source_policy": "prefer_pin_geometry_fallback_parent_instance",
        "start_patch_id": None,
        "end_patch_id": None,
        "touched_patch_ids": [],
        "patch_count": 0,
        "cross_patch_count": 0,
        "path_bbox": None,
        "anchor_source_counts": {
            "exact_pin_geometry": 0,
            "parent_instance_anchor": 0,
            "missing": 0,
        },
        "has_missing_spatial_anchor": True,
        "stage_map_summary": {
            "cell_density": _empty_stat(),
            "pin_density": _empty_stat(),
            "rudy": _empty_stat(),
            "egr_overflow": _empty_stat(),
        },
    }


def _empty_stat() -> dict[str, Any]:
    return {"min": None, "max": None, "avg": None, "count": 0}


def _empty_null_reason() -> dict[str, dict[str, str]]:
    return {
        "identity": {},
        "analysis_context": {},
        "endpoints": {},
        "path_timing": {},
        "path_electrical": {},
        "path_points": {},
        "timing_edges": {},
        "wire_path_nodes": {},
        "path_spatial": {},
        "progressive_metadata": {},
        "source_refs": {},
    }


def _normalized_criticality(
    slack: float | None, min_slack: float | None, max_slack: float | None
) -> tuple[float | None, str | None]:
    if slack is None or min_slack is None or max_slack is None:
        return None, "missing_slack"
    if max_slack == min_slack:
        return None, "constant_slack_range"
    return (max_slack - slack) / (max_slack - min_slack), None


def _stage_slack_summaries(
    rows: list[Any],
) -> dict[tuple[str, str | None], tuple[float | None, float | None]]:
    summaries: dict[tuple[str, str | None], tuple[float | None, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _normalize_analysis_key(row.get("delay_type"), row.get("clock"))
        if key not in summaries:
            summaries[key] = (_to_float(row.get("WNS")), _to_float(row.get("TNS")))
    return summaries


def _slack_ranges_by_analysis_context(
    summaries: list[Any], details: list[Any]
) -> dict[tuple[str, str | None], tuple[float | None, float | None]]:
    values_by_key: dict[tuple[str, str | None], list[float]] = {}
    for idx, item in enumerate(summaries):
        if not isinstance(item, dict):
            continue
        detail = details[idx] if idx < len(details) and isinstance(details[idx], dict) else {}
        slack = _to_float(
            item.get("slack") if item.get("slack") is not None else detail.get("slack")
        )
        if slack is None:
            continue
        values_by_key.setdefault(_analysis_context_key(item, detail), []).append(slack)
    return {key: (min(values), max(values)) for key, values in values_by_key.items() if values}


def _analysis_context_key(
    summary: dict[str, Any], detail: dict[str, Any]
) -> tuple[str, str | None]:
    return _normalize_analysis_key(
        summary.get("delay_type") or detail.get("type"),
        summary.get("clock_group") or detail.get("clock_field"),
    )


def _normalize_analysis_key(delay_type: Any, clock_group: Any) -> tuple[str, str | None]:
    normalized_delay = str(delay_type or "unknown").lower()
    normalized_clock = str(clock_group) if clock_group is not None else None
    return normalized_delay, normalized_clock


def _slack_index(rows: list[Any], clock_group: Any, delay_type: Any) -> int | None:
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if row.get("clock") == clock_group and row.get("delay_type") == delay_type:
            return idx
    return None


def _check_type(delay_type: Any) -> str:
    value = str(delay_type or "").lower()
    if value == "max":
        return "setup"
    if value == "min":
        return "hold"
    return "unknown"


def _transition_from_path_delay(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.endswith("r"):
        return "rise"
    if text.endswith("f"):
        return "fall"
    return None


def _is_clock_pin(pin_name: Any) -> bool:
    return str(pin_name or "").lower() in {"ck", "clk", "clock"}


def _sequence_hash(points: list[dict[str, Any]]) -> str:
    joined = "|".join(str(point.get("pin_key") or point.get("raw_name") or "") for point in points)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _empty_electrical() -> dict[str, Any]:
    return {
        "capacitance_sum": None,
        "capacitance_list": [],
        "max_slew": None,
        "slew_list": [],
        "resistance_sum": None,
        "resistance_list": [],
        "incr_delay_sum": None,
        "incr_delay_list": [],
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None
