"""Performance-check support against real qor_summary gate metrics (no catalog bind)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chipcompiler.engine.signoff.qor_perf_support import (
    analysis_qor_summary_path,
    check_metric,
    load_metric_values,
    load_qor_summary,
    metric_satisfies,
    metric_values_from_summary,
    require_metric,
)


def _gate(gate_id: str, state: str, metrics: list[dict]) -> dict:
    return {
        "id": gate_id,
        "title": gate_id,
        "state": state,
        "blocking": True,
        "metrics": metrics,
        "evidence": [],
    }


def _metric(metric_id: str, actual: float, op: str, expected: float) -> dict:
    return {
        "id": metric_id,
        "actual": actual,
        "operator": op,
        "expected": expected,
    }


def _drc_summary(*, drc_count: float) -> dict:
    passed = drc_count == 0
    return {
        "schema_version": 4,
        "analysis_revision": "quality-gates-v4",
        "analysis_status": "valid",
        "quality_status": "pass" if passed else "fail",
        "gates": [
            _gate(
                "qor.drc.clean",
                "pass" if passed else "failed",
                [_metric("drc_count", drc_count, "==", 0)],
            )
        ],
        "missing_metrics": [],
    }


def _sta_summary(*, setup_wns: float, hold_wns: float, setup_tns: float = 0.0) -> dict:
    setup_ok = setup_wns >= 0 and setup_tns >= 0
    hold_ok = hold_wns >= 0
    return {
        "schema_version": 4,
        "analysis_revision": "quality-gates-v4",
        "analysis_status": "valid",
        "quality_status": "pass" if setup_ok and hold_ok else "fail",
        "gates": [
            _gate(
                "qor.sta.setup_closed",
                "pass" if setup_ok else "failed",
                [
                    _metric("sta_setup_wns", setup_wns, ">=", 0),
                    _metric("sta_setup_tns", setup_tns, ">=", 0),
                ],
            ),
            _gate(
                "qor.sta.hold_closed",
                "pass" if hold_ok else "failed",
                [_metric("sta_hold_wns", hold_wns, ">=", 0)],
            ),
        ],
        "missing_metrics": [],
    }


def test_drc_count_from_summary_and_check():
    summary = _drc_summary(drc_count=3)
    assert require_metric(summary, "drc_count") == pytest.approx(3.0)
    assert check_metric(summary, "drc_count", "==", 0) is False
    assert check_metric(_drc_summary(drc_count=0), "drc_count", "==", 0) is True


def test_sta_timing_metrics_from_summary():
    summary = _sta_summary(setup_wns=-0.01, hold_wns=0.02, setup_tns=-1.0)
    values = metric_values_from_summary(summary)
    assert values["sta_setup_wns"] == pytest.approx(-0.01)
    assert values["sta_setup_tns"] == pytest.approx(-1.0)
    assert values["sta_hold_wns"] == pytest.approx(0.02)
    assert check_metric(summary, "sta_setup_wns", ">=", 0) is False
    assert check_metric(summary, "sta_hold_wns", ">=", 0) is True


def test_load_metric_values_from_analysis_path(tmp_path: Path):
    path = analysis_qor_summary_path(tmp_path, "drc_ecc")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_drc_summary(drc_count=0)), encoding="utf-8")
    assert load_metric_values(path)["drc_count"] == pytest.approx(0.0)
    assert load_qor_summary(path)["quality_status"] == "pass"


def test_metric_satisfies_rejects_unknown_operator():
    assert metric_satisfies(1.0, "==", 1.0) is True
    with pytest.raises(ValueError, match="unsupported"):
        metric_satisfies(1.0, "~~", 1.0)


def test_performance_catalog_ids_are_not_in_summary_metrics():
    summary = _sta_summary(setup_wns=0.0, hold_wns=0.0)
    values = metric_values_from_summary(summary)
    assert "performance.sta.setup_wns" not in values
    assert "sta_setup_wns" in values
