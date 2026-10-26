"""Versioned, unit-aware similarity over stage-visible experience features."""

from __future__ import annotations

import math

SIMILARITY_SCHEMA = "ecc-experience-similarity/1"
MIN_FEATURE_COVERAGE = 0.7


def stage_features(features: dict) -> dict[tuple, float]:
    result: dict[tuple, float] = {}
    for stage in features.get("steps", []):
        if not isinstance(stage, dict):
            continue
        namespace = _namespace(stage.get("step"))
        for metric in stage.get("metrics", []):
            if not isinstance(metric, dict) or metric.get("status") != "available":
                continue
            value = metric.get("value")
            if (
                not isinstance(metric.get("id"), str)
                or not isinstance(metric.get("unit"), str)
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                continue
            key = (
                namespace,
                metric["id"],
                metric["unit"],
                metric.get("scope") or "unknown",
                metric.get("corner") or "unknown",
            )
            result[key] = float(value)
    return result


def feature_distance(
    left_features: dict[tuple, float], right_features: dict[tuple, float]
) -> tuple[float | None, float, list[dict]]:
    common = sorted(left_features.keys() & right_features.keys(), key=str)
    if not common:
        return None, 0.0, []
    denominator = max(len(left_features), len(right_features), 1)
    coverage = len(common) / denominator
    rows = []
    distances = []
    for key in common:
        first, second = left_features[key], right_features[key]
        left_value = _scaled(first)
        right_value = _scaled(second)
        scale = max(abs(left_value), abs(right_value), 1.0)
        distance = abs(left_value - right_value) / scale
        distances.append(distance)
        rows.append(
            {
                "namespace": key[0],
                "id": key[1],
                "unit": key[2],
                "scope": key[3],
                "corner": key[4],
                "query": first,
                "candidate": second,
                "normalized_distance": round(distance, 8),
            }
        )
    return sum(distances) / len(distances), coverage, rows


def parameter_ranges(matches: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[float]] = {}
    for match in matches:
        if match.get("parameter_evidence_level") not in {"applied", "materialized"}:
            continue
        parameters = match.get("parameters", {}).get("values", {})
        if not isinstance(parameters, dict):
            continue
        for key, value in parameters.items():
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                grouped.setdefault(key, []).append(float(value))
    return {
        key: {"min": min(values), "max": max(values), "samples": len(values)}
        for key, values in sorted(grouped.items())
    }


def _scaled(value: float) -> float:
    return math.copysign(math.log1p(abs(value)), value)


def _namespace(step: object) -> str:
    name = str(step or "unknown").casefold().replace("_", "").replace(" ", "")
    if "synthesis" in name or "synth" in name:
        return "synthesis"
    if "floorplan" in name:
        return "floorplan"
    if "place" in name:
        return "place"
    if "cts" in name or "clock" in name:
        return "cts"
    if "route" in name:
        return "route"
    if "sta" in name or "timing" in name:
        return "timing"
    return "other"
