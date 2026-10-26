"""Performance-check support against real qor_summary gate metrics (no catalog bind)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chipcompiler.engine.signoff.qor_perf_support import (
    load_qor_summary,
    metric_values_from_summary,
    require_metric,
)


def _sta_summary(*, setup_wns: float, hold_wns: float) -> dict:
    return {
        "schema_version": 4,
        "analysis_revision": "quality-gates-v4",
        "analysis_status": "valid",
        "quality_status": "pass" if setup_wns >= 0 and hold_wns >= 0 else "fail",
        "gates": [
            {
                "id": "qor.sta.setup_closed",
                "title": "STA setup closure",
                "state": "pass" if setup_wns >= 0 else "failed",
                "blocking": True,
                "metrics": [
                    {
                        "id": "sta_setup_wns",
                        "actual": setup_wns,
                        "operator": ">=",
                        "expected": 0,
                    },
                    {
                        "id": "sta_setup_tns",
                        "actual": 0.0,
                        "operator": ">=",
                        "expected": 0,
                    },
                ],
                "evidence": [],
            },
            {
                "id": "qor.sta.hold_closed",
                "title": "STA hold closure",
                "state": "pass" if hold_wns >= 0 else "failed",
                "blocking": True,
                "metrics": [
                    {
                        "id": "sta_hold_wns",
                        "actual": hold_wns,
                        "operator": ">=",
                        "expected": 0,
                    }
                ],
                "evidence": [],
            },
        ],
        "missing_metrics": [],
    }


def test_metric_values_from_real_shaped_summary():
    summary = _sta_summary(setup_wns=0.05, hold_wns=0.02)
    values = metric_values_from_summary(summary)
    assert values["sta_setup_wns"] == pytest.approx(0.05)
    assert values["sta_hold_wns"] == pytest.approx(0.02)


def test_require_metric_reads_ondisk_summary(tmp_path: Path):
    path = tmp_path / "sta_ecc" / "analysis" / "qor_summary.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_sta_summary(setup_wns=-0.01, hold_wns=0.1)),
        encoding="utf-8",
    )
    summary = load_qor_summary(path)
    assert require_metric(summary, "sta_setup_wns") == pytest.approx(-0.01)
    with pytest.raises(KeyError, match="sta_setup_violation_count"):
        require_metric(summary, "sta_setup_violation_count")


def test_performance_support_does_not_need_catalog_slots():
    # Catalog performance.* ids stay unbound; support reads tool metric ids.
    summary = _sta_summary(setup_wns=0.0, hold_wns=0.0)
    assert "performance.sta.setup_wns" not in metric_values_from_summary(summary)
    assert require_metric(summary, "sta_setup_wns") == 0.0
