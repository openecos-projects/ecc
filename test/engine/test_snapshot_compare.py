from copy import deepcopy

import pytest

from chipcompiler.engine.snapshot_compare import SnapshotComparisonError, compare_snapshots
from chipcompiler.engine.snapshot_qor import build_qor_snapshot_extension


def _snapshot(metrics=None):
    return {
        "schemaVersion": 2,
        "workspaceId": "workspace-gcd",
        "workspaceRevision": 1,
        "flow": {"steps": [{"name": "place", "tool": "ecc", "state": "Success"}]},
        "parameters": {"design": "gcd", "frequency_mhz": 100},
        "checklist": {},
        "signoffAssessment": {},
        "artifacts": [],
        "metrics": metrics or [],
    }


def _metric(metric_id="synthesis_cell_area", value: float = 100, **overrides):
    return {
        "id": metric_id,
        "value": value,
        "scope": "workspace",
        "corner": None,
        "analysis_group": "synthesis",
        **overrides,
    }


@pytest.mark.parametrize(
    ("metric_id", "before", "after", "expected"),
    [
        ("synthesis_cell_area", 100, 80, "improved"),
        ("synthesis_cell_area", 0, 10, "regressed"),
        ("synthesis_cell_area", 100, 100, "unchanged"),
        ("sta_setup_wns", -0.12, -0.08, "improved"),
        ("sta_setup_tns", -1, -2, "regressed"),
        ("route_wirelength", 200, 180, "improved"),
        ("custom_metric", 10, 20, "unknown"),
        ("core_utilization", 0.1, 0.2, "unknown"),
    ],
)
def test_metric_trends_use_canonical_polarity(metric_id, before, after, expected):
    baseline = _snapshot([_metric(metric_id, before)])
    current = _snapshot([_metric(metric_id, after)])

    result = compare_snapshots(baseline, current)

    assert result["metrics"][0]["trend"] == expected
    assert result["summary"]["overall"] == expected
    assert result["metrics"][0]["delta"] == (
        None if metric_id == "custom_metric" else pytest.approx(after - before)
    )


@pytest.mark.parametrize("value", [None, True, "100", float("nan"), float("inf"), 10**400])
def test_invalid_or_missing_numeric_values_are_not_zero(value):
    result = compare_snapshots(_snapshot([_metric(value=value)]), _snapshot([_metric()]))

    assert result["metrics"][0] == {
        "id": "synthesis_cell_area",
        "scope": "workspace",
        "corner": None,
        "analysis_group": "synthesis",
        "baseline_unit": "um^2",
        "current_unit": "um^2",
        "baseline": None,
        "current": 100,
        "delta": None,
        "trend": "unknown",
        "reasons": ["value_unavailable"],
    }


def test_mixed_metrics_and_input_objects_are_unchanged():
    baseline = _snapshot([_metric(value=100), _metric("sta_setup_wns", -0.1)])
    current = _snapshot([_metric(value=90), _metric("sta_setup_wns", -0.2)])
    original = deepcopy((baseline, current))

    result = compare_snapshots(baseline, current)

    assert result["summary"] == {
        "overall": "mixed",
        "scope": "numeric_metrics_and_qor_score_only",
        "counts": {"improved": 1, "regressed": 1, "unchanged": 0, "unknown": 0},
    }
    assert (baseline, current) == original


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"unit": "mm^2"}, "unit_mismatch"),
        ({"direction": "higher_is_better"}, "direction_mismatch"),
        ({"corner_context": {"voltage": 1.2}}, "corner_context_mismatch"),
        ({"project_role": "trend"}, "project_role_mismatch"),
    ],
)
def test_analysis_conditions_disable_trend(overrides, reason):
    baseline = _snapshot([_metric(value=100)])
    current = _snapshot([_metric(value=80, **overrides)])

    metric = compare_snapshots(baseline, current)["metrics"][0]

    assert metric["trend"] == "unknown"
    assert reason in metric["reasons"]
    if reason == "unit_mismatch":
        assert metric["delta"] is None


@pytest.mark.parametrize("constraint", ["frequency_mhz", "clock", "design", "pdk_config"])
def test_constraint_changes_disable_global_judgment(constraint):
    baseline = _snapshot([_metric()])
    current = deepcopy(baseline)
    current["parameters"][constraint] = "different"

    result = compare_snapshots(baseline, current)

    assert result["compatibility"]["comparable"] is False
    assert result["summary"]["overall"] == "unknown"


def test_optimization_parameter_change_does_not_disable_comparison():
    baseline = _snapshot([_metric(value=100)])
    current = _snapshot([_metric(value=80)])
    current["parameters"]["place.target_density"] = 0.3

    result = compare_snapshots(baseline, current)

    assert result["summary"]["overall"] == "improved"
    assert result["parameter_changes"] == [
        {"key": "place.target_density", "baseline": None, "current": 0.3, "change": "added"}
    ]


def test_missing_and_different_corner_metrics_are_not_matched():
    baseline = _snapshot([_metric(corner="slow")])
    current = _snapshot([_metric(corner="fast")])

    result = compare_snapshots(baseline, current)

    assert len(result["metrics"]) == 2
    assert all(metric["delta"] is None for metric in result["metrics"])
    assert result["summary"]["overall"] == "unknown"


def test_duplicate_metric_identity_is_rejected():
    with pytest.raises(SnapshotComparisonError, match="duplicate"):
        compare_snapshots(_snapshot([_metric(), _metric()]), _snapshot())


def test_missing_analysis_identity_is_not_silently_compared():
    metric = _metric()
    del metric["scope"]

    with pytest.raises(SnapshotComparisonError, match="identity"):
        compare_snapshots(_snapshot([metric]), _snapshot([_metric()]))


def test_overflowing_delta_does_not_emit_infinity():
    result = compare_snapshots(
        _snapshot([_metric(value=-1e308)]), _snapshot([_metric(value=1e308)])
    )

    assert result["metrics"][0]["delta"] is None
    assert result["metrics"][0]["reasons"] == ["delta_nonfinite"]
    assert result["summary"]["overall"] == "unknown"


def test_noncanonical_unit_is_not_assumed_to_match_registry():
    before = _snapshot([_metric(value=100, unit="mm^2")])
    after = _snapshot([_metric(value=80, unit="mm^2")])

    metric = compare_snapshots(before, after)["metrics"][0]

    assert metric["delta"] is None
    assert metric["trend"] == "unknown"
    assert metric["reasons"] == ["noncanonical_unit"]


def test_changed_flow_order_disables_numeric_trends():
    baseline = _snapshot([_metric()])
    baseline["flow"]["steps"].append({"name": "route", "tool": "ecc", "state": "Success"})
    current = deepcopy(baseline)
    current["flow"]["steps"].reverse()

    assert compare_snapshots(baseline, current)["compatibility"] == {
        "comparable": False,
        "reasons": ["flow_definition_changed"],
    }


@pytest.mark.parametrize("metrics", [{}, [None], [{"id": []}]])
def test_invalid_metric_projection_is_rejected(metrics):
    baseline = _snapshot()
    baseline["metrics"] = metrics

    with pytest.raises(SnapshotComparisonError):
        compare_snapshots(baseline, _snapshot())


def test_step_and_null_parameter_additions_and_removals():
    baseline = _snapshot()
    current = _snapshot()
    current["flow"]["steps"] = [{"name": "route", "tool": "ecc", "state": "Failed"}]
    baseline["parameters"]["removed"] = None
    current["parameters"]["added"] = None

    result = compare_snapshots(baseline, current)

    assert [step["change"] for step in result["steps"]] == ["removed", "added"]
    assert result["parameter_changes"] == [
        {"key": "added", "baseline": None, "current": None, "change": "added"},
        {"key": "removed", "baseline": None, "current": None, "change": "removed"},
    ]


def test_artifact_identity_is_not_treated_as_content_hash():
    baseline = _snapshot()
    current = _snapshot()
    artifact = {"reference": "output/design.gds", "availability": "available"}
    baseline["artifacts"] = [{**artifact, "artifactId": "old-path-id"}]
    current["artifacts"] = [{**artifact, "artifactId": "new-path-id"}]

    assert compare_snapshots(baseline, current)["artifacts"] == [
        {
            "identity": {"reference": "output/design.gds"},
            "baseline": artifact,
            "current": artifact,
            "change": "unchanged",
            "content_comparison": "unknown",
        }
    ]


def test_qor_score_and_dimension_use_saved_engine_profile():
    baseline = _snapshot()
    baseline["qorSnapshotExtension"] = build_qor_snapshot_extension(
        {
            "scalar_summary": {"score": 70, "status": "YELLOW", "profile": "balanced"},
            "qor_record": {"area": {"value": 70, "state": "PASS", "features": []}},
        },
        [],
    )
    current = deepcopy(baseline)
    current["qorSnapshotExtension"]["score"] = 80
    current["qorSnapshotExtension"]["scalarStatus"] = "GREEN"
    current["qorSnapshotExtension"]["qphys"]["area"]["value"] = 80

    result = compare_snapshots(baseline, current)

    assert result["qor"]["score"]["trend"] == "improved"
    assert result["qor"]["dimensions"][0]["delta"] == 10
    assert result["summary"]["overall"] == "improved"
    current["qorSnapshotExtension"]["profile"] = "low_power"
    assert compare_snapshots(baseline, current)["qor"]["score"]["trend"] == "unknown"


def test_empty_snapshots_do_not_imply_unchanged_quality():
    result = compare_snapshots(_snapshot(), _snapshot())

    assert result["summary"]["overall"] == "unknown"
    assert result["qor"]["status"] == "unavailable"


def test_null_stale_predecessor_is_accepted():
    baseline = _snapshot([_metric()])
    current = deepcopy(baseline)
    current["stalePredecessor"] = None

    assert compare_snapshots(baseline, current)["summary"]["overall"] == "unchanged"


def test_invalidated_step_or_different_workspace_is_explicit():
    baseline = _snapshot([_metric()])
    current = deepcopy(baseline)
    current["workspaceId"] = "other-workspace"
    current["stalePredecessor"] = {"invalidatedStepIds": ["place"]}

    result = compare_snapshots(baseline, current)

    assert result["compatibility"] == {
        "comparable": False,
        "reasons": ["different_workspace", "current_has_invalidated_steps"],
    }
