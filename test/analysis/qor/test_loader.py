import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs
from test.flow_fixture import step_fields


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


_STEP_TOOLS = {"Synthesis": "yosys", "place": "dreamplace"}


_STEP_DIRECTORIES = {
    "Synthesis": "Synthesis_yosys",
    "postFloorplan": "postFloorplan_ecc",
    "place": "place_dreamplace",
    "CTS": "CTS_ecc",
    "route": "route_ecc",
    "drc": "drc_ecc",
    "lvs": "lvs_ecc",
    "RCX": "RCX_ecc",
    "sta": "sta_ecc",
    "powerAnalysis": "powerAnalysis_ecc",
    "Harden": "Harden_ecc",
}


def _make_workspace(tmp_path, steps):
    root = str(tmp_path / "ws")
    _write(
        os.path.join(root, "home", "flow.json"),
        {
            "schema_version": 2,
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
    from chipcompiler.data.workspace_config import save_workspace_config

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
    "Synthesis": SUCCESS,
    "postFloorplan": SUCCESS,
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
        inputs: Any = load_workspace_qor_inputs(workspace)
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
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("place_hpwl") == 111.0
        assert inputs.metrics["place_hpwl"].step == "route"

    def test_stale_payload_of_unstarted_step_is_ignored(self, tmp_path):
        steps = dict(_FULL_FLOW)
        steps["route"] = "Unstart"
        workspace = _make_workspace(tmp_path, steps)
        _write_step_payload(workspace.directory, "route_ecc", [_metric("route_wirelength", 9999.0)])
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.value("route_wirelength") is None
        assert "route" not in inputs.analyzed_steps
        assert inputs.parse_failures == 0  # unstarted steps are not failures

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
        from chipcompiler.data.workspace_config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=50.0, qor_profile="speed_demon")
        assert save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert inputs.profile == "balanced"
        assert inputs.config_warnings

    def test_nonpositive_budget_warns_and_undeclares(self, tmp_path):
        from chipcompiler.data.workspace_config import load_workspace_config, save_workspace_config

        workspace = _make_workspace(tmp_path, _FULL_FLOW)
        parameters = load_workspace_config(workspace.directory)
        parameters.update(frequency_max=50.0, qor_power_budget_w=-1)
        assert save_workspace_config(workspace.directory, parameters)
        inputs: Any = load_workspace_qor_inputs(workspace)
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
        inputs: Any = load_workspace_qor_inputs(workspace)
        assert [corner.setup_ws for corner in inputs.corners] == [16.622, 18.98]

    def test_failed_sta_does_not_load_stale_corner_files(self, tmp_path):
        steps = dict(_FULL_FLOW)
        steps["sta"] = "Imcomplete"
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
                "Synthesis_yosys",
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
            "Synthesis_yosys/feature/post_synthesis/power_summary.json"
        )
        assert inputs.power_source_kind == "synthesis"
        assert inputs.power_corner == "post_synthesis"

    def test_signoff_power_uses_worst_configured_corner(self, tmp_path):
        workspace = _make_workspace(tmp_path, {**_FULL_FLOW, "powerAnalysis": SUCCESS})
        _write(
            os.path.join(
                workspace.directory,
                "powerAnalysis_ecc",
                "feature",
                "powerAnalysis.step.json",
            ),
            {
                "schema_version": 1,
                "step": "powerAnalysis",
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
            "powerAnalysis_ecc/feature/powerAnalysis.step.json"
        )
        assert inputs.power_source_kind == "signoff"
        assert inputs.power_corner == "powerAnalysis"

    def test_power_analysis_summary_replaces_sta_power_source(self, tmp_path):
        steps = {**_FULL_FLOW, "powerAnalysis": SUCCESS}
        workspace = _make_workspace(tmp_path, steps)
        _write(
            os.path.join(
                workspace.directory,
                "powerAnalysis_ecc",
                "feature",
                "powerAnalysis.step.json",
            ),
            {
                "schema_version": 1,
                "step": "powerAnalysis",
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
            "powerAnalysis_ecc/feature/powerAnalysis.step.json"
        )
        assert inputs.power_source_kind == "signoff"
        assert inputs.power_corner == "powerAnalysis"

    def test_incomplete_power_analysis_does_not_score_stale_power_summary(self, tmp_path):
        steps = {**_FULL_FLOW, "powerAnalysis": "Incomplete"}
        workspace = _make_workspace(tmp_path, steps)
        _write(
            os.path.join(
                workspace.directory,
                "powerAnalysis_ecc",
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
