from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def parse_route_native_demand_capacity_artifacts(
    stage_dir: Path, canonical_grid: dict[str, Any]
) -> dict[str, Any]:
    """Parse iRT SpaceRouter-native per-gcell demand/capacity artifacts."""
    for path in _candidate_paths(stage_dir):
        labels = _labels_from_records(_iter_records(path), canonical_grid, path)
        if labels:
            return {"available": True, "source": str(path), "labels": labels}
    return {"available": False, "source": None, "labels": []}


def _candidate_paths(stage_dir: Path) -> list[Path]:
    root = stage_dir / "data" / "rt" / "space_router"
    preferred_names = [
        "route_native_demand_capacity_final.jsonl",
        "route_native_demand_capacity.jsonl",
        "route_native_demand_capacity_final.json",
        "route_native_demand_capacity.json",
    ]
    preferred_paths = [root / name for name in preferred_names]
    globbed_paths = sorted(
        [
            *root.glob("route_native_demand_capacity*.jsonl"),
            *root.glob("route_native_demand_capacity*.json"),
        ]
    )
    return [path for path in [*preferred_paths, *globbed_paths] if path.exists()]


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            yield from _iter_jsonl_records(path)
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))
        return
    if isinstance(payload, dict):
        for key in ("patches", "gcells", "records", "demand_capacity"):
            value = payload.get(key)
            if isinstance(value, list):
                yield from (item for item in value if isinstance(item, dict))
                return


def _iter_jsonl_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _labels_from_records(
    records: Iterable[dict[str, Any]], canonical_grid: dict[str, Any], path: Path
) -> list[dict[str, Any]]:
    patch_totals = {
        int(patch["patch_id"]): {
            "patch_id": int(patch["patch_id"]),
            "row": int(patch["row"]),
            "col": int(patch["col"]),
            "horizontal_demand": 0.0,
            "horizontal_capacity": 0.0,
            "horizontal_demand_capacity": 0.0,
            "vertical_demand": 0.0,
            "vertical_capacity": 0.0,
            "vertical_demand_capacity": 0.0,
            "by_layer": {},
            "source": "irt_space_router_native",
            "source_artifacts": {"route_native_demand_capacity": str(path)},
        }
        for patch in canonical_grid.get("patches", [])
    }
    patches_by_coord = {
        (item["row"], item["col"]): patch_id for patch_id, item in patch_totals.items()
    }

    matched = False
    for record in records:
        patch_id = _record_patch_id(record, canonical_grid, patches_by_coord)
        if patch_id is None or patch_id not in patch_totals:
            continue
        direction = _direction(record)
        if direction is None:
            continue
        demand = _float_or_none(record.get("demand"))
        capacity = _float_or_none(record.get("capacity"))
        if demand is None and capacity is None:
            continue
        demand = demand or 0.0
        capacity = capacity or 0.0
        demand_capacity = demand - capacity
        item = patch_totals[patch_id]
        item[f"{direction}_demand"] += demand
        item[f"{direction}_capacity"] += capacity
        item[f"{direction}_demand_capacity"] += demand_capacity
        layer = str(
            record.get("layer")
            or record.get("layer_name")
            or f"layer_{record.get('layer_idx', 'unknown')}"
        )
        layer_item = item["by_layer"].setdefault(
            layer,
            {
                "horizontal_demand": 0.0,
                "horizontal_capacity": 0.0,
                "horizontal_demand_capacity": 0.0,
                "vertical_demand": 0.0,
                "vertical_capacity": 0.0,
                "vertical_demand_capacity": 0.0,
            },
        )
        layer_item[f"{direction}_demand"] += demand
        layer_item[f"{direction}_capacity"] += capacity
        layer_item[f"{direction}_demand_capacity"] += demand_capacity
        matched = True

    if not matched:
        return []
    labels = []
    for item in patch_totals.values():
        h_margin = item["horizontal_demand_capacity"]
        v_margin = item["vertical_demand_capacity"]
        labels.append(
            {
                **item,
                "union_demand_capacity": max(h_margin, v_margin),
                "horizontal_utilization": _safe_ratio(
                    item["horizontal_demand"], item["horizontal_capacity"]
                ),
                "vertical_utilization": _safe_ratio(
                    item["vertical_demand"], item["vertical_capacity"]
                ),
            }
        )
    return labels


def _record_patch_id(
    record: dict[str, Any],
    canonical_grid: dict[str, Any],
    patches_by_coord: dict[tuple[int, int], int],
) -> int | None:
    raw_patch_id = record.get("patch_id")
    if raw_patch_id is not None:
        try:
            return int(raw_patch_id)
        except (TypeError, ValueError):
            return None
    row = record.get("row")
    col = record.get("col")
    if row is not None and col is not None:
        try:
            return patches_by_coord.get((int(row), int(col)))
        except (TypeError, ValueError):
            return None
    x = record.get("x")
    y = record.get("y")
    if x is None or y is None:
        gcell = record.get("gcell")
        if isinstance(gcell, dict):
            x, y = gcell.get("x"), gcell.get("y")
        elif isinstance(gcell, list | tuple) and len(gcell) >= 2:
            x, y = gcell[0], gcell[1]
    if x is None or y is None:
        return None
    try:
        gcell_key = (int(y), int(x))
    except (TypeError, ValueError):
        return None
    if gcell_key in patches_by_coord:
        return patches_by_coord[gcell_key]
    for patch in canonical_grid.get("patches", []):
        bbox = patch["bbox"]
        x_in_bbox = float(bbox["llx"]) <= float(x) <= float(bbox["urx"])
        y_in_bbox = float(bbox["lly"]) <= float(y) <= float(bbox["ury"])
        if x_in_bbox and y_in_bbox:
            return int(patch["patch_id"])
    return None


def _direction(record: dict[str, Any]) -> str | None:
    value = str(record.get("direction") or record.get("orient") or "").lower()
    if value in {"horizontal", "h", "x", "east", "west"}:
        return "horizontal"
    if value in {"vertical", "v", "y", "south", "north"}:
        return "vertical"
    return None


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
