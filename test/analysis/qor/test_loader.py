import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs


def _write(path, payload):
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
        "source": {"kind": "analysis", "path": "x"},
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


_STEP_DIRECTORIES = {
    "Synthesis": "Synthesis_yosys",
    "Floorplan": "Floorplan_ecc",
    "place": "place_dreamplace",
    "CTS": "CTS_ecc",
    "route": "route_ecc",
    "drc": "drc_ecc",
    "lvs": "lvs_ecc",
    "RCX": "RCX_ecc",
    "sta": "sta_ecc",
    "Harden": "Harden_ecc",
}


def _make_workspace(tmp_path, steps):
    root = str(tmp_path / "ws")
    _write(
        os.path.join(root, "home", "flow.json"),
        {"steps": [{"name": name, "tool": "ecc", "state": state} for name, state in steps.items()]},
    )
    _write(
        os.path.join(root, "home", "parameters.json"),
        {"Design": "gcd", "frequency_max": 50.0},
    )
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
    "Synthesis": SUCCESS,
    "Floorplan": SUCCESS,
    "place": SUCCESS,
    "CTS": SUCCESS,
    "route": SUCCESS,
    "drc": SUCCESS,
    "lvs": SUCCESS,
    "RCX": SUCCESS,
    "sta": SUCCESS,
    "Harden": SUCCESS,
}


class TestMetricSelection:
    def test_role_priority_final_beats_trend(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "place_ecc".replace("place_ecc", "place_dreamplace"),
            [_metric("place_hpwl", 100.0, project_role="trend")],
        )
        _write_step_payload(
            workspace.directory,
            "route_ecc",
            [_metric("place_hpwl", 200.0, project_role="final")],
        )
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 200.0

    def test_later_step_wins_within_same_role(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write_step_payload(
            workspace.directory,
            "place_dreamplace",
            [_metric("place_hpwl", 100.0, project_role="trend")],
        )
        _write_step_payload(
            workspace.directory,
            "route_ecc",
            [_metric("place_hpwl", 111.0, project_role="trend")],
        )
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 111.0
        assert inputs.metrics["place_hpwl"].step == "route"

    def test_stale_payload_of_unstarted_step_is_ignored(self, tmp_path):
        steps = dict(_FULL_FLOW)
        steps["route"] = "Unstart"
        workspace = _make_workspace(tmp_path, steps)
        _write_step_payload(workspace.directory, "route_ecc", [_metric("route_wirelength", 9999.0)])
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.value("route_wirelength") is None
        assert "route" not in inputs.analyzed_steps
        assert inputs.parse_failures == 0  # unstarted steps are not failures

    def test_failed_payload_counts_as_parse_failure(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(workspace.directory, "drc_ecc", "analysis", "qor_metrics.json"),
            {"broken": True},
        )
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.parse_failures == 1
        assert "drc" not in inputs.analyzed_steps


class TestParameterResolution:
    def test_frequency_max_resolves_tclk(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.tclk_ns == pytest.approx(20.0)
        assert inputs.config_warnings == []

    def test_unknown_profile_warns_and_falls_back(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(workspace.directory, "home", "parameters.json"),
            {"frequency_max": 50.0, "qor_profile": "speed_demon"},
        )
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.profile == "balanced"
        assert inputs.config_warnings

    def test_nonpositive_budget_warns_and_undeclares(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        _write(
            os.path.join(workspace.directory, "home", "parameters.json"),
            {"frequency_max": 50.0, "qor_power_budget_w": -1},
        )
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.power_budget_uw is None
        assert inputs.config_warnings


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
        inputs = load_workspace_qor_inputs(workspace)
        assert [corner.setup_ws for corner in inputs.corners] == [16.622, 18.98]


class TestDesignResolution:
    def test_design_falls_back_to_parameters(self, tmp_path):
        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        workspace.design = SimpleNamespace(name="")
        workspace.name = ""
        inputs = load_workspace_qor_inputs(workspace)
        assert inputs.design == "gcd"
