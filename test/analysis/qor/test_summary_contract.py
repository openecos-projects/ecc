from chipcompiler.analysis.qor.summary_contract import (
    gate_reason,
    is_supported_summary,
    summary_gates,
    summary_missing_metrics,
    summary_quality_status,
)


def test_v4_summary_is_read_from_current_fields():
    summary = {
        "schema_version": 4,
        "quality_status": "blocked",
        "gates": [
            {
                "id": "qor.sta.hold_closed",
                "title": "STA hold closure",
                "state": "failed",
                "blocking": True,
                "metrics": [
                    {
                        "id": "sta_hold_wns",
                        "actual": -0.121,
                        "operator": ">=",
                        "expected": 0,
                    }
                ],
                "evidence": [],
            }
        ],
        "missing_metrics": [{"metric_id": "sta_hold_wns", "reason": "missing"}],
    }

    assert is_supported_summary(summary)
    assert summary_quality_status(summary) == "blocked"
    assert summary_gates(summary) == summary["gates"]
    assert summary_missing_metrics(summary) == summary["missing_metrics"]
    assert gate_reason(summary["gates"][0]) == "sta_hold_wns=-0.121 (required >= 0)"


def test_unknown_summary_schema_is_not_supported():
    assert not is_supported_summary({"schema_version": 2})
    assert summary_quality_status({"schema_version": 2, "status": "pass"}) is None
    assert summary_gates({"schema_version": 2, "hard_gates": []}) == []
