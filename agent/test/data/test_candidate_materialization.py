from pathlib import Path
from unittest.mock import ANY

import pytest

from agent.data.candidate_capabilities import export_candidate_capabilities
from agent.data.candidate_materialization import (
    CandidateMaterializationError,
    candidate_knob_registry,
    materialize_candidate_config,
    reapply_materialized_candidate_config,
    validate_materialized_candidate_config,
)
from agent.data.candidate_registry import candidate_capability_registry
from agent.test.data import candidate_workspace as cw
from test.flow_fixture import step_fields


def test_registry_covers_the_declared_public_physical_knobs():
    knob_ids = {knob.knob_id for knob in candidate_knob_registry()}

    assert {
        "floorplan.core_util",
        "floorplan.aspect_ratio",
        "floorplan.core_margin",
        "cts.max_fanout",
        "place.target_density",
        "place.target_overflow",
        "place.cell_padding_x",
        "place.routability_opt",
        "place.density_weight",
        "route.bottom_layer",
        "route.top_layer",
        "route.thread_number",
        "route.enable_timing",
        "cts.skew_bound",
    }.issubset(knob_ids)
    assert "design.frequency_mhz" not in knob_ids
    assert "place.global_right_padding" not in knob_ids
    assert "floorplan.auto_pin_layer" not in knob_ids
    assert "filler.min_filler_width" not in knob_ids
    assert "place.timing_opt" not in knob_ids
    assert {knob.knob_id for knob in candidate_capability_registry()} == {
        knob.knob_id for knob in candidate_knob_registry()
    } | {
        "place.timing_opt",
        "place.enable_net_weighting",
        "place.pin2pin_weight",
        "cts.max_length",
        "cts.use_netlist",
        "cts.net_list",
    }


def test_materialize_cts_overlay_preserves_base_config_and_writes_receipt(tmp_path):
    workspace = cw.workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "cts",
        [{"knob_id": "cts.skew_bound", "value": 0.12}],
        candidate_id="cts-rerun-001",
    )

    cts_path = workspace.config["cts"]
    config = cw.read_json(cts_path)
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    persisted = cw.read_json(receipt_path)

    assert config["skew_bound"] == 0.12
    assert config["max_fanout"] == "32"
    assert config["buffer_type"] == ["BUF_1"]
    assert config["unrelated"] == {"keep": True}
    assert receipt == persisted
    assert receipt["schema"] == "ecc.workspace.candidate_materialization.v1"
    assert receipt["schema_version"] == 1
    assert receipt["candidate_id"] == "cts-rerun-001"
    assert receipt["target_step"] == "cts"
    assert receipt["target"] == {"step": "cts"}
    assert receipt["patch"] == [{"knob_id": "cts.skew_bound", "value": 0.12}]
    assert receipt["registry_sha256"].startswith("sha256:")
    assert receipt["patch_sha256"].startswith("sha256:")
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert receipt["configs"] == [
        {
            "config_key": "cts",
            "ref": "config/cts_ecc.json",
            "before_sha256": ANY,
            "after_sha256": cw.sha256(cts_path),
        }
    ]


def test_dreamplace_knob_materializes_as_a_target_step_value(tmp_path):
    workspace = cw.workspace(tmp_path)
    baseline = workspace.config["dreamplace"].read_bytes()

    receipt = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_overflow", "value": 0.07}],
        candidate_id="place-candidate",
    )

    snapshot = receipt["snapshots"][0]
    params_path = tmp_path / "home" / "params.toml"
    core = {"utilitization": 0.6, "aspect_ratio": 1.0, "margin": [2, 2]}
    assert workspace.config["dreamplace"].read_bytes() == baseline
    assert cw.read_params(params_path) == {
        "core": core,
        "step_params": {"placement": {"place.stop_overflow": 0.07}},
    }
    assert receipt["configs"] == [
        {
            "config_key": "parameters",
            "ref": "home/params.toml",
            "before_sha256": snapshot["before_sha256"],
            "after_sha256": cw.sha256(params_path),
        }
    ]
    assert cw.read_params(tmp_path / snapshot["before_ref"]) == {"core": core}
    assert (tmp_path / snapshot["after_ref"]).read_bytes() == params_path.read_bytes()


def test_reapply_restores_the_dreamplace_step_value(tmp_path):
    from chipcompiler.data.parameter import load_parameter
    from chipcompiler.data.workspace_config import save_workspace_config

    workspace = cw.workspace(tmp_path)
    receipt = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.routability_opt", "value": False}],
        candidate_id="place-candidate",
    )
    params_path = tmp_path / "home" / "params.toml"
    assert save_workspace_config(tmp_path, {"core": {"utilitization": 0.6}})

    assert reapply_materialized_candidate_config(workspace, "placement") == receipt
    assert workspace.parameters.data == load_parameter(params_path).data
    assert workspace.parameters.data["step_params"] == {
        "placement": {"place.routability_opt_flag": 0}
    }


def test_materialize_rejects_multiple_knobs_without_writing_artifacts(tmp_path):
    workspace = cw.workspace(tmp_path)
    before = cw.read_json(workspace.config["cts"])

    with pytest.raises(CandidateMaterializationError, match="exactly one knob"):
        materialize_candidate_config(
            workspace,
            "cts",
            [
                {"knob_id": "cts.skew_bound", "value": 0.12},
                {"knob_id": "cts.max_fanout", "value": 48},
            ],
            candidate_id="multi-knob-candidate",
        )

    assert cw.read_json(workspace.config["cts"]) == before
    assert not (tmp_path / "analysis" / "candidate_materialization.v1.json").exists()


def test_materialize_rejects_noop_without_writing_artifacts(tmp_path):
    from chipcompiler.data.workspace_config import save_workspace_config

    workspace = cw.workspace(tmp_path)
    assert save_workspace_config(
        tmp_path, {"step_params": {"placement": {"place.target_density": 0.8}}}
    )
    params_path = tmp_path / "home" / "params.toml"
    before = params_path.read_bytes()

    with pytest.raises(CandidateMaterializationError, match="did not change config"):
        materialize_candidate_config(
            workspace,
            "placement",
            [{"knob_id": "place.target_density", "value": 0.8}],
            candidate_id="noop-candidate",
        )

    assert params_path.read_bytes() == before
    assert not (tmp_path / "analysis" / "candidate_materialization.v1.json").exists()
    assert not (tmp_path / "analysis" / "candidate_config_snapshots.v1").exists()


def test_materialize_rejects_baseline_value_without_writing_artifacts(tmp_path):
    workspace = cw.workspace(tmp_path)
    params_path = tmp_path / "home" / "params.toml"
    before = params_path.read_bytes()

    # The DreamPlace baseline holds target_density 0.8 and no step value is stored.
    with pytest.raises(CandidateMaterializationError, match="did not change config"):
        materialize_candidate_config(
            workspace,
            "placement",
            [{"knob_id": "place.target_density", "value": 0.8}],
            candidate_id="baseline-noop-candidate",
        )

    assert params_path.read_bytes() == before
    assert not (tmp_path / "analysis" / "candidate_materialization.v1.json").exists()
    assert not (tmp_path / "analysis" / "candidate_config_snapshots.v1").exists()


def test_materialize_converts_padding_sites_to_written_dbu(tmp_path):
    workspace = cw.workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.cell_padding_x", "value": 2}],
        candidate_id="padding-candidate",
    )

    assert cw.read_params(tmp_path / "home" / "params.toml")["step_params"] == {
        "placement": {"place.cell_padding_x": 400}
    }
    assert receipt["patch"] == [{"knob_id": "place.cell_padding_x", "value": 400}]


@pytest.mark.parametrize(
    "target_step,patch",
    [
        ("cts", [{"knob_id": "legalization.bndry_padding_x", "value": 20000}]),
        ("cts", [{"knob_id": "cts.max_fanout", "value": True}]),
        ("cts", [{"knob_id": "cts.buffer_type", "value": ["NOT_A_PDK_BUFFER"]}]),
        ("filler", [{"knob_id": "filler.min_filler_width", "value": 2}]),
        ("placement", [{"knob_id": "place.timing_opt", "value": True}]),
        ("cts", [{"knob_id": "cts.skew_bound", "value": 0.1, "extra": "reject"}]),
    ],
)
def test_materialize_rejects_out_of_contract_patches(tmp_path, target_step, patch):
    workspace = cw.workspace(tmp_path)

    with pytest.raises(CandidateMaterializationError):
        materialize_candidate_config(
            workspace,
            target_step,
            patch,
            candidate_id="invalid-candidate",
        )


@pytest.mark.parametrize("candidate_id", ["", "bad id", "../candidate"])
def test_materialize_rejects_invalid_candidate_id(tmp_path, candidate_id):
    workspace = cw.workspace(tmp_path)

    with pytest.raises(CandidateMaterializationError):
        materialize_candidate_config(
            workspace,
            "cts",
            [{"knob_id": "cts.skew_bound", "value": 0.1}],
            candidate_id=candidate_id,
        )


def test_export_capabilities_returns_stable_schema_and_backend_truth_without_writing_catalog(
    tmp_path,
):
    workspace = cw.workspace(tmp_path)

    capabilities = export_candidate_capabilities(workspace)

    cts = next(item for item in capabilities["targets"] if item["target_step"] == "cts")
    legalization = next(
        item for item in capabilities["targets"] if item["target_step"] == "legalization"
    )
    filler = next(item for item in capabilities["targets"] if item["target_step"] == "filler")
    floorplan = next(item for item in capabilities["targets"] if item["target_step"] == "floorplan")

    assert not (tmp_path / "analysis" / "candidate_capabilities.v1.json").exists()
    assert capabilities["schema"] == "ecc.workspace.candidate_capabilities.v1"
    assert capabilities["schema_version"] == 1
    assert capabilities["registry_sha256"].startswith("sha256:")
    assert cts["backend"]["available"] is True
    skew_bound = next(knob for knob in cts["knobs"] if knob["knob_id"] == "cts.skew_bound")
    assert skew_bound["minimum"] == 0.0
    assert skew_bound["maximum"] == 1.0
    assert legalization["backend"] == {
        "tool": "dreamplace",
        "expected_tool": "dreamplace",
        "adapter": "legalization_dreamplace",
        "available": True,
    }
    assert legalization["knobs"] == []
    assert filler["backend"]["available"] is False
    assert filler["candidate_generation"] is False
    assert filler["knobs"] == []
    assert filler["unavailable_knobs"] == []
    assert "PDN.Grid" in floorplan["excluded_configuration_groups"]
    assert "Floorplan.Auto place pin" in floorplan["excluded_configuration_groups"]


def test_native_legalization_backend_is_fail_closed_for_candidates(tmp_path):
    workspace = cw.workspace(tmp_path)
    legalization = next(
        step for step in workspace.flow.data["steps"] if step["name"] == "legalization"
    )
    legalization["tool"] = "ecc"

    capabilities = export_candidate_capabilities(workspace)
    target = next(item for item in capabilities["targets"] if item["target_step"] == "legalization")

    assert target["candidate_generation"] is False
    assert target["backend"]["tool"] == "ecc"
    assert target["backend"]["expected_tool"] == "dreamplace"
    with pytest.raises(CandidateMaterializationError, match="not candidate-capable"):
        materialize_candidate_config(
            workspace,
            "legalization",
            [{"knob_id": "legalization.bndry_padding_x", "value": 4}],
            candidate_id="native-legalization-candidate",
        )


def test_materialized_candidate_rejects_backend_drift_before_execution(tmp_path):
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.6}],
        candidate_id="placement-candidate",
    )
    placement = next(step for step in workspace.flow.data["steps"] if step["name"] == "placement")
    placement["tool"] = "ecc"

    with pytest.raises(CandidateMaterializationError, match="not candidate-capable"):
        validate_materialized_candidate_config(workspace, "placement")


def test_duplicate_workspace_target_is_fail_closed_for_candidates(tmp_path):
    workspace = cw.workspace(tmp_path)
    workspace.flow.data["steps"].append(
        {
            "name": "legalization",
            "tool": "dreamplace",
            **step_fields("legalization", "dreamplace"),
        }
    )

    capabilities = export_candidate_capabilities(workspace)
    target = next(item for item in capabilities["targets"] if item["target_step"] == "legalization")

    assert target["candidate_generation"] is False
    with pytest.raises(CandidateMaterializationError, match="not candidate-capable"):
        materialize_candidate_config(
            workspace,
            "legalization",
            [{"knob_id": "legalization.bndry_padding_x", "value": 4}],
            candidate_id="duplicate-legalization-candidate",
        )


def test_materialize_floorplan_patch_preserves_the_canonical_core_tree(tmp_path):
    """A parameters patch lands in the canonical core subtree: no parallel
    Core key, and the untouched members survive the save/load round trip."""
    workspace = cw.workspace(tmp_path)

    materialize_candidate_config(
        workspace,
        "floorplan",
        [{"knob_id": "floorplan.core_util", "value": 0.7}],
        candidate_id="floorplan-candidate",
    )

    from chipcompiler.data.parameter import load_parameter

    reloaded = load_parameter(Path(workspace.parameters.path)).data
    assert "Core" not in reloaded
    assert reloaded["core"] == {"utilitization": 0.7, "aspect_ratio": 1.0, "margin": [2, 2]}
    assert "Core" not in workspace.parameters.data
    assert workspace.parameters.data["core"]["utilitization"] == 0.7


def test_materialize_rejects_missing_parameters_base_config(tmp_path):
    """A missing canonical config is not an empty base: patching it would
    recreate the TOML with only the patch keys, dropping the workspace
    identity — fail closed instead."""
    workspace = cw.workspace(tmp_path)
    Path(workspace.parameters.path).unlink()

    with pytest.raises(CandidateMaterializationError, match="missing candidate base config"):
        materialize_candidate_config(
            workspace,
            "floorplan",
            [{"knob_id": "floorplan.core_util", "value": 0.7}],
            candidate_id="missing-base",
        )
