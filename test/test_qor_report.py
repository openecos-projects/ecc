import json
import os

from chipcompiler.engine.qor_report import (
    QorMetricRecord,
    build_qor_report,
    generate_qor_report,
    score_record,
)
from chipcompiler.engine.signoff.report_checklist import (
    build_checklist_report,
    generate_checklist_report,
)


def _record(**overrides):
    base = dict(
        step="STA",
        metric_name="sta_setup_wns",
        display_name="STA Setup WNS",
        value=-0.1,
        unit="ns",
        dimension="timing",
        polarity="higher_is_better",
        scope="all_configured_corners",
        project_role="final",
        rating_score=True,
    )
    base.update(overrides)
    return QorMetricRecord(**base)


class TestScoreRecord:
    def test_slack_metrics(self):
        assert score_record(_record(metric_name="sta_setup_wns", value=0.05)) == 100.0
        assert score_record(_record(metric_name="sta_setup_wns", value=-0.1)) == 50.0
        assert score_record(_record(metric_name="sta_setup_wns", value=-0.2)) == 0.0
        assert score_record(_record(metric_name="sta_setup_wns", value=-0.5)) == 0.0  # clamped

    def test_lower_is_better(self):
        assert (
            score_record(
                _record(
                    metric_name="drc_count",
                    value=0,
                    dimension="routability_physical",
                    polarity="lower_is_better",
                )
            )
            == 100.0
        )
        assert (
            score_record(
                _record(
                    metric_name="drc_count",
                    value=5,
                    dimension="routability_physical",
                    polarity="lower_is_better",
                )
            )
            == 50.0
        )

    def test_target_range_core_utilization(self):
        record = _record(
            metric_name="core_utilization",
            value=0.55,
            dimension="area_cost",
            polarity="target_range",
            step="Harden",
        )
        assert score_record(record) == 100.0
        low = _record(
            metric_name="core_utilization",
            value=0.225,
            dimension="area_cost",
            polarity="target_range",
            step="Harden",
        )
        assert score_record(low) == 50.0

    def test_trend_only_and_unknown_are_not_scored(self):
        assert score_record(_record(polarity="trend_only")) is None
        assert score_record(_record(metric_name="not_a_scored_metric")) is None


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def _metrics_payload(metrics):
    return {
        "schema_version": 3,
        "kind": "qor_metrics",
        "metrics": metrics,
    }


def _metric(metric_id, value, **overrides):
    base = dict(
        id=metric_id,
        display_name=metric_id,
        value=value,
        unit="",
        category="timing",
        direction="lower_is_better",
        scope="project",
        corner=None,
        project_role="final",
        step_role="primary",
        rating={"gate": False, "score": True, "trend": True},
    )
    base.update(overrides)
    return base


def _make_workspace(tmp_path, *, with_metrics=True, with_checklist=True):
    root = tmp_path / "ws"
    _write(
        root / "home" / "flow.json",
        {
            "steps": [
                {"name": "route", "tool": "ecc", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
                {"name": "lvs", "tool": "ecc", "state": "Success"},
                {"name": "RCX", "tool": "ecc", "state": "Success"},
                {"name": "sta", "tool": "ecc", "state": "Success"},
                {"name": "Harden", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write(root / "home" / "parameters.json", {"Design": "gcd", "PDK": "ics55"})
    if with_metrics:
        _write(
            root / "drc_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload(
                [
                    _metric("drc_count", 0, category="routability_physical"),
                    _metric("route_dr_total_violation_count", 10, category="routability_physical"),
                ]
            ),
        )
        _write(
            root / "sta_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload(
                [
                    _metric("sta_setup_wns", -0.1, direction="higher_is_better", unit="ns"),
                    _metric(
                        "sta_setup_wns",
                        -0.1,
                        direction="higher_is_better",
                        unit="ns",
                        corner="MAX_125",
                    ),
                ]
            ),
        )
        _write(
            root / "Harden_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload(
                [
                    _metric(
                        "core_utilization", 0.55, category="area_cost", direction="target_range"
                    ),
                    _metric("die_area", 1500, category="area_cost"),
                ]
            ),
        )
    if with_checklist:
        _write(
            root / "home" / "checklist.json",
            {
                "schema_version": 3,
                "kind": "signoff_checklist",
                "checker_revision": "signoff-v1",
                "generated_at": "2026-01-01T00:00:00Z",
                "status": "attention",
                "summary": {"passed": 2, "blocked": 1, "attention": 1, "unavailable": 0},
                "checklist": [
                    {
                        "id": "flow.route",
                        "step": "route",
                        "category": "flow",
                        "title": "Routing complete",
                        "policy": "block",
                        "state": "pass",
                        "blocked": False,
                        "summary": "ok",
                        "source": {},
                        "evidence": [],
                    },
                    {
                        "id": "quality.drc.clean",
                        "step": "drc",
                        "category": "quality",
                        "title": "DRC clean",
                        "policy": "block",
                        "state": "failed",
                        "blocked": True,
                        "summary": "drc_count=2 (required == 0)",
                        "source": {},
                        "evidence": ["drc_ecc/analysis/qor_summary.json"],
                    },
                    {
                        "id": "harden.gds",
                        "step": "Harden",
                        "category": "artifact",
                        "title": "Harden GDS",
                        "policy": "warn",
                        "state": "warning",
                        "blocked": False,
                        "summary": "optional file missing",
                        "source": {},
                        "evidence": [],
                    },
                    {
                        "id": "sta.corner",
                        "step": "sta",
                        "category": "quality",
                        "title": "Corner coverage",
                        "policy": "block",
                        "state": "pass",
                        "blocked": False,
                        "summary": "",
                        "source": {},
                        "evidence": [],
                    },
                ],
            },
        )

    class _Flow:
        def __init__(self, data):
            self.data = data

    class _Workspace:
        directory = str(root)
        name = "gcd"
        design = type("D", (), {"name": "gcd"})()
        with open(root / "home" / "flow.json") as f:
            flow_data = json.load(f)
        flow = _Flow(flow_data)

    return _Workspace()


class TestBuildQorReport:
    def test_dimension_scores_and_weighted_overall(self, tmp_path):
        report = build_qor_report(_make_workspace(tmp_path))
        by_label = {d.label: d for d in report.dimension_scores}
        # routability: drc_count=0 -> 100, route_drc=10/50 -> 80 => avg 90
        assert by_label["Routability / Physical"].score == 90.0
        # timing: sta_setup_wns -0.1 -> 50 (both corner records dedup? no:
        # different corners are distinct keys, both 50) => 50
        assert by_label["Timing"].score == 50.0
        # area: utilization 100, die_area 1500/3000 -> 50 => 75
        assert by_label["Area"].score == 75.0
        # GUI rule: weights are NOT renormalized over missing dimensions.
        assert report.overall_score == round(50.0 * 0.35 + 90.0 * 0.2 + 75.0 * 0.1, 1)
        assert report.status == "Green"
        assert report.gate_status == "pass"
        assert report.area_scoring_step == "Harden"

    def test_corner_records_are_distinct(self, tmp_path):
        report = build_qor_report(_make_workspace(tmp_path))
        sta_rows = [m for m in report.metrics if m.metric_name == "sta_setup_wns"]
        assert len(sta_rows) == 2

    def test_trend_only_records_are_not_selected_for_score(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        _write(
            os.path.join(workspace.directory, "drc_ecc", "analysis", "qor_metrics.json"),
            _metrics_payload(
                [
                    _metric("drc_count", 0, category="routability_physical"),
                    _metric(
                        "drc_count",
                        7,
                        category="routability_physical",
                        project_role="trend",
                        rating={"gate": False, "score": False, "trend": True},
                    ),
                ]
            ),
        )
        report = build_qor_report(workspace)
        by_label = {d.label: d for d in report.dimension_scores}
        assert by_label["Routability / Physical"].metric_count == 1

    def test_empty_workspace_report(self, tmp_path):
        report = build_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert report.overall_score is None
        assert report.status in ("Blocked", "Green")
        text = generate_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert "NOT RATED" in text
        assert "no project-level QoR metrics available" in text

    def test_text_report_layout(self, tmp_path):
        text = generate_qor_report(_make_workspace(tmp_path))
        assert "ECC QOR OVERALL SCORE" in text
        assert "[ DIMENSION SCORES ]" in text
        assert "[ METRIC SCORES ]" in text
        assert "sta_setup_wns" in text
        assert "END OF QOR REPORT" in text
        assert "weights not renormalized" in text


class TestChecklistReport:
    def test_build_from_checklist_json(self, tmp_path):
        report = build_checklist_report(_make_workspace(tmp_path))
        assert report.available is True
        assert report.status == "attention"
        assert len(report.items) == 4
        assert len(report.blocked_items) == 1
        assert report.blocked_items[0].id == "quality.drc.clean"
        assert len(report.attention_items) == 1

    def test_unavailable_when_missing(self, tmp_path):
        report = build_checklist_report(_make_workspace(tmp_path, with_checklist=False))
        assert report.available is False

    def test_text_report(self, tmp_path):
        text = generate_checklist_report(_make_workspace(tmp_path))
        assert "ECC SIGNOFF CHECKLIST REPORT" in text
        assert "ATTENTION" in text
        assert "quality.drc.clean" not in text  # table shows titles, not ids
        assert "DRC clean" in text
        assert "evidence: drc_ecc/analysis/qor_summary.json" in text
        assert "END OF CHECKLIST REPORT" in text

    def test_unavailable_text(self, tmp_path):
        text = generate_checklist_report(_make_workspace(tmp_path, with_checklist=False))
        assert "Checklist unavailable" in text
