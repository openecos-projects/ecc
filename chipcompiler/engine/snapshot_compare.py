"""Pure comparison of committed Snapshot facts, not live workspace contents."""

from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY
from chipcompiler.utility import finite_number


class SnapshotComparisonError(ValueError):
    """A snapshot projection cannot be compared unambiguously."""


def compare_snapshots(baseline: dict, current: dict) -> dict:
    steps = _compare_records(
        baseline["flow"].get("steps", []), current["flow"].get("steps", []), ("name", "tool")
    )
    reasons = _context_reasons(baseline, current)
    metrics = _compare_metrics(baseline, current, reasons)
    qor = _compare_qor(baseline, current, reasons)
    trends = [metric["trend"] for metric in metrics]
    if qor["score"]["baseline"] is not None or qor["score"]["current"] is not None:
        trends.append(qor["score"]["trend"])
    return {
        "schema_version": 1,
        "baseline": _identity(baseline),
        "current": _identity(current),
        "summary": {
            "overall": _overall(trends),
            "scope": "numeric_metrics_and_qor_score_only",
            "counts": {
                trend: trends.count(trend)
                for trend in ("improved", "regressed", "unchanged", "unknown")
            },
        },
        "compatibility": {"comparable": not reasons, "reasons": reasons},
        "steps": steps,
        "metrics": metrics,
        "qor": qor,
        "parameter_changes": _mapping_changes(baseline["parameters"], current["parameters"]),
        "configuration_changes": _mapping_changes(
            {key: baseline.get(key) for key in ("workspaceSpec", "workspaceBindings")},
            {key: current.get(key) for key in ("workspaceSpec", "workspaceBindings")},
        ),
        "signoff": _pair(baseline["signoffAssessment"], current["signoffAssessment"]),
        "checklist": _pair(baseline["checklist"], current["checklist"]),
        "artifacts": [
            {**item, "content_comparison": "unknown"}
            for item in _compare_records(
                baseline["artifacts"], current["artifacts"], ("reference",), omit=("artifactId",)
            )
        ],
        "warnings": [
            "Artifact IDs identify paths, not content; no historical content hash is available.",
            "Comparability uses saved metadata only; RTL, PDK and SDC contents are not verified.",
            "Overall is a numeric trend summary, not a signoff or tapeout decision.",
        ],
    }


def _identity(snapshot: dict) -> dict:
    return {
        "workspace_id": snapshot["workspaceId"],
        "workspace_revision": snapshot["workspaceRevision"],
        "schema_version": snapshot["schemaVersion"],
    }


def _context_reasons(baseline: dict, current: dict) -> list[str]:
    reasons = []
    if baseline["workspaceId"] != current["workspaceId"]:
        reasons.append("different_workspace")
    if [(step.get("name"), step.get("tool")) for step in baseline["flow"].get("steps", [])] != [
        (step.get("name"), step.get("tool")) for step in current["flow"].get("steps", [])
    ]:
        reasons.append("flow_definition_changed")
    for key in ("workspaceSpec", "workspaceBindings"):
        before = baseline.get(key, {})
        after = current.get(key, {})
        for section in ("design", "inputs", "pdk"):
            if before.get(section) != after.get(section):
                reasons.append(f"{key}.{section}_changed")
    for key in sorted(baseline["parameters"].keys() | current["parameters"].keys()):
        if any(
            token in key.lower()
            for token in ("design", "top", "clock", "frequency", "period", "sdc", "pdk", "corner")
        ) and baseline["parameters"].get(key) != current["parameters"].get(key):
            reasons.append(f"constraint_parameter_changed:{key}")
    for role, snapshot in (("baseline", baseline), ("current", current)):
        if (snapshot.get("stalePredecessor") or {}).get("invalidatedStepIds"):
            reasons.append(f"{role}_has_invalidated_steps")
    return reasons


def _index(records: object, keys: tuple[str, ...]) -> dict:
    if not isinstance(records, list):
        raise SnapshotComparisonError(f"expected an array for {keys}")
    indexed = {}
    for record in records:
        if not isinstance(record, dict):
            raise SnapshotComparisonError(f"expected an object for {keys}")
        identity = tuple(record.get(key) for key in keys)
        if any(
            (not isinstance(value, str) or not value) and not (key == "corner" and value is None)
            for key, value in zip(keys, identity, strict=True)
        ):
            raise SnapshotComparisonError(f"invalid record identity for {keys}")
        if identity in indexed:
            raise SnapshotComparisonError(f"duplicate record identity: {identity}")
        indexed[identity] = record
    return indexed


def _compare_records(
    baseline: list, current: list, keys: tuple[str, ...], *, omit: tuple[str, ...] = ()
) -> list[dict]:
    before = _index(baseline, keys)
    after = _index(current, keys)
    result = []
    for identity in sorted(before.keys() | after.keys(), key=str):
        first = before.get(identity)
        second = after.get(identity)
        first = {key: value for key, value in first.items() if key not in omit} if first else None
        second = (
            {key: value for key, value in second.items() if key not in omit} if second else None
        )
        result.append({"identity": dict(zip(keys, identity, strict=True)), **_pair(first, second)})
    return result


def _pair(baseline: object, current: object) -> dict:
    if baseline is None:
        change = "added" if current is not None else "unavailable"
    elif current is None:
        change = "removed"
    else:
        change = "unchanged" if baseline == current else "changed"
    return {"baseline": baseline, "current": current, "change": change}


def _mapping_changes(baseline: dict, current: dict) -> list[dict]:
    changes = []
    for key in sorted(baseline.keys() | current.keys()):
        if key in baseline and key in current and baseline[key] == current[key]:
            continue
        pair = _pair(baseline.get(key), current.get(key))
        if key not in baseline:
            pair["change"] = "added"
        elif key not in current:
            pair["change"] = "removed"
        else:
            pair["change"] = "changed"
        changes.append({"key": key, **pair})
    return changes


def _numeric_pair(baseline: object, current: object, direction: str, reasons: list[str]) -> dict:
    before = finite_number(baseline)
    after = finite_number(current)
    reasons = list(reasons)
    if before is None or after is None:
        reasons.append("value_unavailable")
    delta = finite_number(after - before) if before is not None and after is not None else None
    if delta is None and before is not None and after is not None:
        reasons.append("delta_nonfinite")
    if direction not in {"higher_is_better", "lower_is_better"}:
        reasons.append("direction_unknown")
    trend = "unknown"
    if not reasons and delta is not None:
        if delta == 0:
            trend = "unchanged"
        elif (delta > 0) == (direction == "higher_is_better"):
            trend = "improved"
        else:
            trend = "regressed"
    return {
        "baseline": before,
        "current": after,
        "delta": delta,
        "trend": trend,
        "reasons": reasons,
    }


def _compare_metrics(baseline: dict, current: dict, context_reasons: list[str]) -> list[dict]:
    keys = ("id", "scope", "corner", "analysis_group")
    before = _index(
        baseline.get("metrics", baseline.get("qorAssessment", {}).get("metrics", [])), keys
    )
    after = _index(
        current.get("metrics", current.get("qorAssessment", {}).get("metrics", [])), keys
    )
    result = []
    for identity in sorted(before.keys() | after.keys(), key=str):
        first = before.get(identity, {})
        second = after.get(identity, {})
        unit, direction = METRIC_REGISTRY.get(identity[0], (None, "unknown"))
        first_unit = first.get("unit", unit)
        second_unit = second.get("unit", unit)
        reasons = list(context_reasons)
        if first_unit is None or second_unit is None:
            reasons.append("unit_unknown")
        elif first_unit != second_unit:
            reasons.append("unit_mismatch")
        elif unit is not None and first_unit != unit:
            reasons.append("noncanonical_unit")
        for key in ("direction", "corner_context", "project_role"):
            if first.get(key) != second.get(key):
                reasons.append(f"{key}_mismatch")
        if first.get("direction", direction) != direction:
            reasons.append("noncanonical_direction")
        numeric = _numeric_pair(first.get("value"), second.get("value"), direction, reasons)
        if (
            "unit_mismatch" in reasons
            or "unit_unknown" in reasons
            or "noncanonical_unit" in reasons
        ):
            numeric["delta"] = None
        result.append(
            {
                **dict(zip(keys, identity, strict=True)),
                "baseline_unit": first_unit,
                "current_unit": second_unit,
                **numeric,
            }
        )
    return result


def _compare_qor(baseline: dict, current: dict, context_reasons: list[str]) -> dict:
    first = baseline.get("qorSnapshotExtension", {})
    second = current.get("qorSnapshotExtension", {})
    reasons = list(context_reasons)
    if first.get("status") != "available" or second.get("status") != "available":
        reasons.append("qor_unavailable")
    for key in ("schemaVersion", "scoringEngine", "profile"):
        if first.get(key) != second.get(key):
            reasons.append(f"qor_{key}_mismatch")
    dimensions = []
    first_dimensions = first.get("qphys", {})
    second_dimensions = second.get("qphys", {})
    for name in sorted(first_dimensions.keys() | second_dimensions.keys()):
        before = first_dimensions.get(name, {})
        after = second_dimensions.get(name, {})
        dimension_reasons = list(reasons)
        if before.get("state") == "UNKNOWN" or after.get("state") == "UNKNOWN":
            dimension_reasons.append("dimension_unavailable")
        if before.get("featureIds") != after.get("featureIds"):
            dimension_reasons.append("dimension_features_mismatch")
        dimensions.append(
            {
                "dimension": name,
                **_numeric_pair(
                    before.get("value"), after.get("value"), "higher_is_better", dimension_reasons
                ),
            }
        )
    return {
        "status": "available" if "qor_unavailable" not in reasons else "unavailable",
        "score": _numeric_pair(
            first.get("score"), second.get("score"), "higher_is_better", reasons
        ),
        "dimensions": dimensions,
        "changes": _mapping_changes(
            {key: value for key, value in first.items() if key != "artifactIds"},
            {key: value for key, value in second.items() if key != "artifactIds"},
        ),
    }


def _overall(trends: list[str]) -> str:
    if not trends or "unknown" in trends:
        return "unknown"
    if "improved" in trends and "regressed" in trends:
        return "mixed"
    if "regressed" in trends:
        return "regressed"
    if "improved" in trends:
        return "improved"
    return "unchanged"
