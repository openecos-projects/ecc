from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_drc_artifacts(stage_dir: Path) -> dict[str, Any]:
    violation_path, metric_path = _drc_artifact_paths(stage_dir)
    violations = _parse_violation_map(violation_path)
    metrics = _read_json(metric_path)
    metric_count = _to_int(metrics.get("drc_num"))
    return {
        "available": violation_path.exists() or metric_count is not None,
        "violations": violations,
        "metrics": metrics,
        "count": sum(int(item.get("count") or 1) for item in violations)
        if violations
        else (metric_count or 0),
        "source": str(violation_path),
        "metrics_source": str(metric_path),
    }


def _drc_artifact_paths(stage_dir: Path) -> tuple[Path, Path]:
    if stage_dir.name == "drc_final_ecc":
        return (
            stage_dir / "data" / "drc_final" / "violation_map.json",
            stage_dir / "analysis" / "drc_final_metrics.json",
        )
    return (
        stage_dir / "data" / "drc" / "violation_map.json",
        stage_dir / "analysis" / f"{stage_dir.name.split('_', 1)[0]}_metrics.json",
    )


def _parse_violation_map(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    raw_items = (
        payload
        if isinstance(payload, list)
        else payload.get("violations", [])
        if isinstance(payload, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item)
        out.append(
            {
                "id": idx,
                "type": str(
                    item.get("type") or item.get("violation_type") or item.get("rule") or "unknown"
                ),
                "rule": item.get("rule"),
                "layer": item.get("layer"),
                "bbox": bbox,
                "count": int(item.get("count") or 1),
                "source": str(path),
                "null_reason": {} if bbox else {"bbox": "missing_violation_bbox"},
            }
        )
    return out


def _bbox(item: dict[str, Any]) -> dict[str, float] | None:
    raw = item.get("bbox") or item.get("box") or item.get("rect")
    if isinstance(raw, dict):
        try:
            return {
                "llx": float(raw["llx"]),
                "lly": float(raw["lly"]),
                "urx": float(raw["urx"]),
                "ury": float(raw["ury"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, list | tuple) and len(raw) >= 4:
        try:
            return {
                "llx": float(raw[0]),
                "lly": float(raw[1]),
                "urx": float(raw[2]),
                "ury": float(raw[3]),
            }
        except (TypeError, ValueError):
            return None
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
