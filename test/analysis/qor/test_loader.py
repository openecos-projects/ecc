import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs
from test.analysis.qor.helpers import touch_qor_evidence
from test.flow_fixture import step_fields


def _write(path, payload):
    if str(path).endswith("qor_metrics.json"):
        touch_qor_evidence(path, payload)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def _metric(metric_id, value, project_role="final", **overrides):
    record = {
        "id": metric_id,
        "display_name": metric_id,
        "value": value,
        "unit": "",
        "category": "timing",
        "direction": "lower_is_better",
        "scope": "project",
        "corner": None,
        "project_role": project_role,
        "step_role": "primary",
        "rating": {"gate": False, "score": True, "trend": True},
        "source": {"kind": "analysis", "path": "feature/x.json"},
    }
    record.update(overrides)
    return record


def _payload(metrics):
    return {
        "schema_version": 3,
        "kind": "qor_metrics",
        "integrity": {"status": "pass", "invalid_metric_source_ids": [], "invalid_detail_ids": []},
        "metrics": metrics,
    }


def _write_step_payload(root, directory, metrics):
    _write(
        os.path.join(root, directory, "analysis", "qor_metrics.json"),
        _payload(metrics),
    )


_STEP_TOOLS = {"synthesis": "yosys", "placement": "dreamplace"}


_STEP_DIRECTORIES = {
    "synthesis": "synthesis_yosys",
    "post_floorplan": "post_floorplan_ecc",
    "placement": "placement_dreamplace",
    "cts": "cts_ecc",
    "routing": "routing_ecc",
    "drc": "drc_ecc",
    "lvs": "lvs_ecc",
    "rcx": "rcx_ecc",
    "sta": "sta_ecc",
    "power_analysis": "power_analysis_ecc",
    "harden": "harden_ecc",
}


def _make_workspace(tmp_path, steps):
    root = str(tmp_path / "ws")
    _write(
        os.path.join(root, "home", "flow.json"),
        {
            "schema_version": 3,
            "steps": [
                {
                    "name": name,
                    "tool": _STEP_TOOLS.get(name, "ecc"),
                    "state": state,
                    **step_fields(name, _STEP_TOOLS.get(name, "ecc")),
                }
                for name, state in steps.items()
            ],
        },
    )
    from chipcompiler.data.workspace.config import save_workspace_config

    assert save_workspace_config(root, {"design": "gcd", "frequency_max": 50.0})
    # Every successful step emits a minimal valid payload unless a test
    # overwrites it; the loader treats a missing payload as a parse failure.
    for step_value, state in steps.items():
        if state == SUCCESS:
            _write_step_payload(root, _STEP_DIRECTORIES[step_value], [_metric("probe_metric", 1.0)])

    class _Flow:
        data = {}

    return SimpleNamespace(
        directory=root, name="gcd", design=SimpleNamespace(name="gcd"), flow=_Flow()
    )


SUCCESS = "Success"

_FULL_FLOW = {
    "synthesis": SUCCESS,
    "post_floorplan": SUCCESS,
    "placement": SUCCESS,
    "cts": SUCCESS,
    "routing": SUCCESS,
    "drc": SUCCESS,
    "lvs": SUCCESS,
    "rcx": SUCCESS,
    "sta": SUCCESS,
    "harden": SUCCESS,
}


class TestMetricSelection:
    def test_role_priority_final_beats_trend(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "place_ecc".replace("place_ecc", "placement_dreamplace"),
            [_metric("place_hpwl", 100.0, project_role="trend")],
        )
        _write_step_payload(
            workspace.directory,
            "routing_ecc",
            [_metric("place_hpwl", 200.0, project_role="final")],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 200.0

    def test_later_step_wins_within_same_role(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "placement_dreamplace",
            [_metric("place_hpwl", 100.0, project_role="trend")],
        )
        _write_step_payload(
            workspace.directory,
            "routing_ecc",
            [_metric("place_hpwl", 111.0, project_role="trend")],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 111.0
        assert inputs.metrics["place_hpwl"].step == "routing"

    def test_conflicting_duplicate_record_is_unknown_and_warned(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [_metric("drc_count", 0.0), _metric("drc_count", 999.0)],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("drc_count" in w and "conflicting" in w for w in inputs.config_warnings)

    def test_identical_duplicate_record_is_harmless(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [_metric("drc_count", 0.0), _metric("drc_count", 0.0)],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") == 0.0
        assert inputs.config_warnings == []

    def test_better_role_record_overrides_conflicting_duplicates(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "placement_dreamplace",
            [
                _metric("place_hpwl", 1.0, project_role="trend"),
                _metric("place_hpwl", 2.0, project_role="trend"),
            ],
        )
        _write_step_payload(
            workspace.directory,
            "routing_ecc",
            [_metric("place_hpwl", 200.0, project_role="final")],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 200.0
        assert inputs.config_warnings == []

    def test_same_step_cross_role_conflict_is_unknown(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [
                _metric("drc_count", 0.0, project_role="gate"),
                _metric("drc_count", 2.0, project_role="trend"),
            ],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("conflicting" in w for w in inputs.config_warnings)

    def test_stale_payload_of_unstarted_step_is_ignored(self, tmp_path):
        steps = dict(_FULL_FLOW)
        steps["routing"] = "Unstart"
        workspace = _make_workspace(tmp_path, steps)
        _write_step_payload(
            workspace.directory, "routing_ecc", [_metric("route_wirelength", 9999.0)]
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("route_wirelength") is None
        assert "routing" not in inputs.analyzed_steps
        assert inputs.parse_failures == 0  # unstarted steps are not failures

    def test_step_skipped_from_the_ledger_contributes_nothing(self, tmp_path):
        steps = {name: state for name, state in _FULL_FLOW.items() if name != "cts"}
        workspace = _make_workspace(tmp_path, steps)
        _write_step_payload(workspace.directory, "cts_ecc", [_metric("cts_skew", 9999.0)])
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("cts_skew") is None
        assert "cts" not in inputs.analyzed_steps
        assert inputs.parse_failures == 0

    def test_failed_payload_counts_as_parse_failure(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(workspace.directory, "drc_ecc", "analysis", "qor_metrics.json"),
            {"broken": True},
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.parse_failures == 1
        assert "drc" not in inputs.analyzed_steps


class TestParameterResolution:
    def test_frequency_max_resolves_tclk(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.tclk_ns == pytest.approx(20.0)
        assert inputs.config_warnings == []

    def test_unknown_profile_warns_and_falls_back(self, tmp_path):
        from chipcompiler.data.workspace.config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=50.0, qor_profile="speed_demon")
        assert save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.profile == "balanced"
        assert inputs.config_warnings

    def test_nonpositive_budget_warns_and_undeclares(self, tmp_path):
        from chipcompiler.data.workspace.config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=50.0, qor_power_budget_w=-1)
        assert save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.power_budget_uw is None
        assert inputs.config_warnings

    def test_infinite_budget_warns_and_undeclares(self, tmp_path):
        from chipcompiler.data.workspace.config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=50.0, qor_power_budget_w=float("inf"))
        save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.power_budget_uw is None
        assert inputs.config_warnings

    def test_nonfinite_frequency_max_warns(self, tmp_path):
        from chipcompiler.data.workspace.config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=float("inf"))
        save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.tclk_ns is None
        assert any("frequency_max" in w for w in inputs.config_warnings)


class TestCornerLoading:
    def test_per_corner_summaries_are_parsed(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        for corner_dir, wns in (("MAX_125_t125", 16.622), ("MAX_M40_tm40", 18.98)):
            _write(
                os.path.join(
                    workspace.directory,
                    "sta_ecc",
                    "feature",
                    corner_dir,
                    "Cworst",
                    "qor_summary.json",
                ),
                {
                    "path_groups": [],
                    "summary": {
                        "setup": {"wns": wns, "tns": 0.0, "nvp": 0, "frequency_mhz": 296.0},
                        "hold": {"wns": 0.1, "tns": 0.0, "nvp": 0},
                    },
                },
            )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert [corner.setup_ws for corner in inputs.corners] == [16.622, 18.98]

    def test_failed_sta_does_not_load_stale_corner_files(self, tmp_path):
        steps = dict(_FULL_FLOW)
        steps["sta"] = "Incomplete"
        workspace = _make_workspace(tmp_path, steps)
        _write(
            os.path.join(
                workspace.directory,
                "sta_ecc",
                "feature",
                "MAX_125_t125",
                "Cworst",
                "qor_summary.json",
            ),
            {
                "path_groups": [],
                "summary": {
                    "setup": {"wns": 1.0, "tns": 0.0, "nvp": 0, "frequency_mhz": 50.0},
                    "hold": {"wns": 1.0, "tns": 0.0, "nvp": 0},
                },
            },
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.corners == []

    def test_synthesis_power_summary_is_loaded(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(
                workspace.directory,
                "synthesis_yosys",
                "feature",
                "post_synthesis",
                "power_summary.json",
            ),
            {
                "schema_version": 1,
                "dynamic_uw": 3.0,
                "leakage_uw": 4.0,
                "internal_uw": 1.0,
                "switching_uw": 2.0,
            },
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.power_total_uw == 7.0
        assert inputs.power_source_path.endswith(
            "synthesis_yosys/feature/post_synthesis/power_summary.json"
        )
        assert inputs.power_source_kind == "synthesis"
        assert inputs.power_corner == "post_synthesis"

    def test_signoff_power_uses_worst_configured_corner(self, tmp_path):
        workspace = _make_workspace(tmp_path, {**_FULL_FLOW, "power_analysis": SUCCESS})
        _write(
            os.path.join(
                workspace.directory,
                "power_analysis_ecc",
                "feature",
                "power_analysis.step.json",
            ),
            {
                "schema_version": 1,
                "step": "power_analysis",
                "power_summary": {
                    "schema_version": 1,
                    "dynamic_uw": 8.0,
                    "leakage_uw": 1.0,
                    "internal_uw": 2.0,
                    "switching_uw": 6.0,
                },
            },
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.power_total_uw == 9.0
        assert inputs.power_source_path.endswith(
            "power_analysis_ecc/feature/power_analysis.step.json"
        )
        assert inputs.power_source_kind == "signoff"
        assert inputs.power_corner == "power_analysis"

    def test_power_analysis_summary_replaces_sta_power_source(self, tmp_path):
        steps = {**_FULL_FLOW, "power_analysis": SUCCESS}
        workspace = _make_workspace(tmp_path, steps)
        _write(
            os.path.join(
                workspace.directory,
                "power_analysis_ecc",
                "feature",
                "power_analysis.step.json",
            ),
            {
                "schema_version": 1,
                "step": "power_analysis",
                "power_summary": {
                    "schema_version": 1,
                    "dynamic_uw": 8.0,
                    "leakage_uw": 1.0,
                    "internal_uw": 2.0,
                    "switching_uw": 6.0,
                },
            },
        )
        # A current workspace must not fall back to the old STA location.
        _write(
            os.path.join(
                workspace.directory,
                "sta_ecc",
                "feature",
                "MAX_125",
                "Cworst",
                "power_summary.json",
            ),
            {
                "schema_version": 1,
                "dynamic_uw": 90.0,
                "leakage_uw": 10.0,
                "internal_uw": 20.0,
                "switching_uw": 70.0,
            },
        )

        inputs: Any = load_workspace_qor_inputs(workspace)

        assert inputs.power_total_uw == 9.0
        assert inputs.power_source_path.endswith(
            "power_analysis_ecc/feature/power_analysis.step.json"
        )
        assert inputs.power_source_kind == "signoff"
        assert inputs.power_corner == "power_analysis"

    def test_incomplete_power_analysis_does_not_score_stale_power_summary(self, tmp_path):
        steps = {**_FULL_FLOW, "power_analysis": "Incomplete"}
        workspace = _make_workspace(tmp_path, steps)
        _write(
            os.path.join(
                workspace.directory,
                "power_analysis_ecc",
                "feature",
                "power_summary.json",
            ),
            {
                "schema_version": 1,
                "dynamic_uw": 8.0,
                "leakage_uw": 1.0,
                "internal_uw": 2.0,
                "switching_uw": 6.0,
            },
        )

        inputs: Any = load_workspace_qor_inputs(workspace)

        assert inputs.power_total_uw is None

    def test_setup_only_corner_is_loaded_with_fallback_marker(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(
                workspace.directory,
                "sta_ecc",
                "feature",
                "MAX_125_t125",
                "Cworst",
                "qor_summary.json",
            ),
            {
                "path_groups": [],
                "summary": {"setup": {"wns": 1.0, "tns": 0.0, "nvp": 0}},
            },
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert len(inputs.corners) == 1
        assert inputs.sta_setup_only is True

    def test_corner_with_float_violation_count_is_not_loaded(self, tmp_path):
        # An unparseable corner must be absent (never silently coerced) so the
        # gates see fewer loaded corners than expected and report UNKNOWN.
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(
                workspace.directory,
                "sta_ecc",
                "feature",
                "MAX_125_t125",
                "Cworst",
                "qor_summary.json",
            ),
            {
                "path_groups": [],
                "summary": {
                    "setup": {"wns": -0.5, "tns": 0.0, "nvp": 3.5, "frequency_mhz": 296.0},
                    "hold": {"wns": 0.1, "tns": 0.0, "nvp": 0},
                },
            },
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.corners == []


class TestMetricRangeValidation:
    @pytest.mark.parametrize("bad", [52.0, -0.3, 0.0])
    def test_out_of_range_utilization_is_unknown_with_warning(self, tmp_path, bad):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "placement_dreamplace",
            [_metric("core_utilization", bad), _metric("place_hpwl", 10.0)],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("core_utilization") is None
        assert inputs.value("place_hpwl") == 10.0
        assert any("core_utilization" in w and "out of range" in w for w in inputs.config_warnings)

    def test_negative_count_is_unknown(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(workspace.directory, "routing_ecc", [_metric("drc_count", -1.0)])
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("drc_count" in w for w in inputs.config_warnings)

    def test_valid_values_and_signed_slack_are_kept(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "placement_dreamplace",
            [
                _metric("core_utilization", 1.0),
                _metric("place_rudy_utilization_max", 1.4),
                _metric("sta_setup_wns", -2.5),
            ],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("core_utilization") == 1.0
        assert inputs.value("place_rudy_utilization_max") == 1.4
        assert inputs.value("sta_setup_wns") == -2.5
        assert inputs.config_warnings == []


class TestDesignResolution:
    def test_design_falls_back_to_parameters(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        workspace.design = SimpleNamespace(name="")
        workspace.name = ""
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.design == "gcd"


def _index_step_directories(root: Path) -> None:
    """Move each step directory to its indexed name and record it in the ledger."""
    from chipcompiler.data.step import STEP_DIRECTORIES

    flow_path = root / "home" / "flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    for index, record in enumerate(flow["steps"], start=1):
        legacy = STEP_DIRECTORIES[record["name"]]
        record["directory"] = f"{index:02d}_{legacy}"
        if (root / legacy).is_dir():
            (root / legacy).rename(root / record["directory"])
    flow_path.write_text(json.dumps(flow), encoding="utf-8")


def test_indexed_step_directories_score_like_the_legacy_layout(tmp_path):
    from chipcompiler.analysis.qor import build_qor_analysis
    from test.analysis.qor.test_reference_gcd import _make_gcd_workspace

    legacy = build_qor_analysis(_make_gcd_workspace(tmp_path / "legacy"))
    workspace = _make_gcd_workspace(tmp_path / "indexed")
    _index_step_directories(Path(workspace.directory))

    indexed = build_qor_analysis(workspace)

    assert (indexed.feasibility, indexed.qor_record, indexed.scalar_summary) == (
        legacy.feasibility,
        legacy.qor_record,
        legacy.scalar_summary,
    )
    assert indexed.evidence == legacy.evidence


class TestGateEvidence:
    """Gate metrics require an existing evidence artifact no newer than qor_metrics.json."""

    def _workspace(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [
                _metric(
                    "drc_count", 0, project_role="gate", source={"path": "feature/drc.step.json"}
                ),
                _metric("drc_trend", 5, project_role="trend", source={"path": "feature/gone.json"}),
            ],
        )
        evidence = os.path.join(workspace.directory, "drc_ecc", "feature", "drc.step.json")
        os.makedirs(os.path.dirname(evidence), exist_ok=True)
        with open(evidence, "w") as f:
            f.write("{}")
        cache = os.path.join(workspace.directory, "drc_ecc", "analysis", "qor_metrics.json")
        return workspace, evidence, cache

    def test_present_and_older_evidence_keeps_gate_metric(self, tmp_path):
        workspace, evidence, cache = self._workspace(tmp_path)
        mtime = os.stat(cache).st_mtime - 10
        os.utime(evidence, (mtime, mtime))
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") == 0
        assert not inputs.config_warnings

    def test_missing_evidence_drops_gate_metric(self, tmp_path):
        workspace, evidence, _ = self._workspace(tmp_path)
        os.remove(evidence)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("drc_count" in w and "missing" in w for w in inputs.config_warnings)

    def test_evidence_newer_than_cache_drops_gate_metric(self, tmp_path):
        workspace, evidence, cache = self._workspace(tmp_path)
        mtime = os.stat(cache).st_mtime + 60
        os.utime(evidence, (mtime, mtime))
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("stale" in w for w in inputs.config_warnings)

    def test_small_mtime_skew_is_tolerated(self, tmp_path):
        workspace, evidence, cache = self._workspace(tmp_path)
        mtime = os.stat(cache).st_mtime + 0.5
        os.utime(evidence, (mtime, mtime))
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") == 0

    def test_missing_source_path_drops_gate_metric(self, tmp_path):
        workspace, _, _ = self._workspace(tmp_path)
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [_metric("drc_count", 0, project_role="gate", source={})],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None

    @pytest.mark.parametrize("bad_rel", ["/etc/passwd", "../outside.json"])
    def test_evidence_path_escape_drops_gate_metric(self, tmp_path, bad_rel):
        workspace, _, _ = self._workspace(tmp_path)
        (tmp_path / "outside.json").write_text("{}")
        _write_step_payload(
            workspace.directory,
            "drc_ecc",
            [_metric("drc_count", 0, project_role="gate", source={"path": bad_rel})],
        )
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_count") is None
        assert any("invalid evidence path" in w for w in inputs.config_warnings)

    def test_non_gate_metrics_are_not_checked(self, tmp_path):
        workspace, _, _ = self._workspace(tmp_path)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("drc_trend") == 5


class TestEgrOverflowGrid:
    def _workspace(
        self,
        tmp_path,
        grid_rows,
        *,
        recorded_exists=False,
        map_filename="placement.map.json",
    ):
        workspace = _make_workspace(tmp_path, {"placement": SUCCESS})
        feature = os.path.join(workspace.directory, "placement_dreamplace", "feature")
        os.makedirs(os.path.join(feature, "egr_congestion_map"))
        csv_path = os.path.join(feature, "egr_congestion_map", "place_egr_union_overflow.csv")
        with open(csv_path, "w") as f:
            f.write("\n".join(grid_rows) + "\n")
        # Stale absolute paths happen when a workspace is moved: prefer the CSV beside the map.
        recorded = csv_path if recorded_exists else "/nonexistent/place_egr_union_overflow.csv"
        _write(
            os.path.join(feature, map_filename),
            {"Congestion": {"map": {"egr": {"union": recorded}}}},
        )
        return workspace

    @pytest.mark.parametrize("map_filename", ["placement.map.json", "place.map.json"])
    def test_grid_size_and_overflowed_cells(self, tmp_path, map_filename):
        inputs: Any = load_workspace_qor_inputs(
            self._workspace(tmp_path, ["0,0,3,0", "0,1,0,0"], map_filename=map_filename)
        )
        assert inputs.egr_gcell_count == 8
        assert inputs.egr_overflowed_gcell_count == 2
        assert inputs.egr_grid_source_path.endswith("place_egr_union_overflow.csv")

    def test_invalid_cell_leaves_grid_unknown(self, tmp_path):
        inputs: Any = load_workspace_qor_inputs(self._workspace(tmp_path, ["0,nan,0", "0,0,0"]))
        assert inputs.egr_gcell_count is None
        assert inputs.egr_overflowed_gcell_count is None

    def test_missing_map_leaves_grid_unknown(self, tmp_path):
        inputs: Any = load_workspace_qor_inputs(_make_workspace(tmp_path, {"placement": SUCCESS}))
        assert inputs.egr_gcell_count is None
