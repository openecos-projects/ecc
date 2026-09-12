import json
import os
from types import SimpleNamespace

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
                        "evidence": [
                            {"kind": "feature", "path": "drc_ecc/analysis/qor_summary.json"}
                        ],
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

    def test_stale_metrics_of_unstarted_steps_do_not_score(self, tmp_path):
        # Invalidation resets a step to Unstart but keeps its analysis
        # outputs on disk; the obsolete metrics must not score.
        workspace = _make_workspace(tmp_path)
        for step in workspace.flow.data["steps"]:
            if step["name"] == "drc":
                step["state"] = "Unstart"

        report = build_qor_report(workspace)

        assert [m for m in report.metrics if m.step == "DRC"] == []
        by_label = {d.label: d for d in report.dimension_scores}
        assert "Routability / Physical" not in by_label

    def test_empty_workspace_report(self, tmp_path):
        report = build_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert report.overall_score is None
        assert report.status == "Blocked"
        text = generate_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert "NOT RATED" in text
        assert "no project-level QoR metrics available" in text

    def test_uses_loaded_workspace_parameters(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        workspace.name = ""
        workspace.design = SimpleNamespace(name="")
        workspace.parameters = SimpleNamespace(data={"design": "from_params"})

        assert build_qor_report(workspace).design == "from_params"

    def test_text_report_layout(self, tmp_path):
        text = generate_qor_report(_make_workspace(tmp_path))
        assert "ECC QOR OVERALL SCORE" in text
        assert "[ DIMENSION SCORES ]" in text
        assert "[ METRIC SCORES ]" in text
        assert "sta_setup_wns" in text
        assert "END OF QOR REPORT" in text
        assert "weights not renormalized" in text


class TestFlowStepOrder:
    def test_flow_steps_follow_the_canonical_chain_order(self):
        from chipcompiler.engine.qor_report import FLOW_STEPS

        assert FLOW_STEPS == (
            "Synth",
            "PostFloorplan",
            "Place",
            "CTS",
            "Legal",
            "Route",
            "Filler",
            "RCX",
            "STA",
            "LVS",
            "DRC",
            "Harden",
        )

    def test_area_scoring_uses_the_latest_scored_step_in_chain_order(self):
        from chipcompiler.engine.qor_report import QorMetricRecord, _resolve_area_scoring_step

        def record(step):
            return QorMetricRecord(
                step=step,
                metric_name="die_area",
                display_name="die_area",
                value=1.0,
                dimension="area_cost",
                rating_score=True,
            )

        flow_states = {"STA": "Success", "DRC": "Success"}
        assert _resolve_area_scoring_step([record("STA"), record("DRC")], flow_states) == "DRC"


class TestFlowCompletionState:
    def test_states_are_derived_explicitly(self):
        from chipcompiler.engine.qor_report import _flow_completion_state

        assert _flow_completion_state([]) == "not_started"
        assert _flow_completion_state(["Unstart"]) == "not_started"
        assert _flow_completion_state(["Success", "Ongoing"]) == "running"
        assert _flow_completion_state(["Success", "Unstart"]) == "in_progress"
        assert _flow_completion_state(["Success", "Incomplete"]) == "failed"
        assert _flow_completion_state(["Invalid"]) == "failed"
        assert _flow_completion_state(["Success"] * 5) == "complete"
        # A legacy persisted Warning (removed terminal state) is unfinished.
        assert _flow_completion_state(["Success", "Warning"]) == "in_progress"

    def test_nonterminal_workspaces_are_blocked(self, tmp_path):
        for state in ("Ongoing", "Unstart", "Pending"):
            workspace = _make_workspace(tmp_path / state, with_metrics=False)
            flow = workspace.flow.data
            for step in flow["steps"][:3]:
                step["state"] = state
            report = build_qor_report(workspace)
            assert report.status == "Blocked", state


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
