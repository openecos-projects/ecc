import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from chipcompiler.data.candidate_capabilities import export_candidate_capabilities
from chipcompiler.data.candidate_materialization import (
    CandidateMaterializationError,
    candidate_knob_registry,
    materialize_candidate_config,
    reapply_materialized_candidate_config,
    validate_materialized_candidate_config,
)
from chipcompiler.data.candidate_registry import candidate_capability_registry


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _workspace(tmp_path: Path):
    cts_path = tmp_path / "config" / "cts_default_config.json"
    pl_path = tmp_path / "config" / "pl_default_config.json"
    _write_json(
        cts_path,
        {
            "skew_bound": "0.08",
            "max_fanout": "32",
            "buffer_type": ["BUF_1"],
            "unrelated": {"keep": True},
        },
    )
    _write_json(
        pl_path,
        {
            "PL": {
                "GP": {"target_density": 0.8},
                "LG": {"max_displacement": 1000000, "global_right_padding": 0},
                "Filler": {
                    "first_iter": ["FILL_2", "FILL_1"],
                    "second_iter": ["FILL_1"],
                    "min_filler_width": 1,
                },
            }
        },
    )
    _write_json(
        tmp_path / "config" / "fp_default_config.json",
        {"Floorplan": {"Tap distance": 58}},
    )
    _write_json(
        tmp_path / "config" / "no_default_config_fixfanout.json",
        {"insert_buffer": "BUF_1", "max_fanout": 32},
    )
    _write_json(
        tmp_path / "config" / "dreamplace.json",
        {
            "target_density": 0.8,
            "stop_overflow": 0.1,
            "cell_padding_x": 0,
            "bndry_padding_x": 0,
            "bndry_padding_y": 0,
            "detailed_place_flag": 0,
            "num_threads": 8,
            "deterministic_flag": 1,
        },
    )
    _write_json(
        tmp_path / "config" / "rt_default_config.json",
        {"RT": {"-bottom_routing_layer": "MET2", "-top_routing_layer": "MET5"}},
    )
    parameters_path = tmp_path / "home" / "parameters.json"
    _write_json(
        parameters_path,
        {"Core": {"Utilitization": 0.6, "Aspect ratio": 1.0, "Margin": [2, 2]}},
    )
    return SimpleNamespace(
        directory=str(tmp_path),
        config={
            "CTS": cts_path,
            "Floorplan": tmp_path / "config" / "fp_default_config.json",
            "fixFanout": tmp_path / "config" / "no_default_config_fixfanout.json",
            "dreamplace": tmp_path / "config" / "dreamplace.json",
            "legalization": pl_path,
            "filler": pl_path,
            "route": tmp_path / "config" / "rt_default_config.json",
        },
        pdk=SimpleNamespace(buffers=["BUF_1", "BUF_2"], fillers=["FILL_1", "FILL_2"]),
        parameters=SimpleNamespace(path=parameters_path),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Floorplan", "tool": "ecc"},
                    {"name": "fixFanout", "tool": "ecc"},
                    {"name": "place", "tool": "dreamplace"},
                    {"name": "CTS", "tool": "ecc"},
                    {"name": "legalization", "tool": "dreamplace"},
                    {"name": "route", "tool": "ecc"},
                    {"name": "filler", "tool": "ecc"},
                ]
            }
        ),
    )


def test_registry_covers_the_declared_public_physical_knobs():
    knob_ids = {knob.knob_id for knob in candidate_knob_registry()}

    assert {
        "floorplan.core_util",
        "floorplan.aspect_ratio",
        "floorplan.core_margin",
        "synth.max_fanout",
        "fixfanout.insert_buffer",
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
        "legalization.detailed_place_flag",
        "legalization.bndry_padding_x",
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
    workspace = _workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "CTS",
        [
            {"knob_id": "cts.max_fanout", "value": 48},
            {"knob_id": "cts.buffer_type", "value": ["BUF_2"]},
            {"knob_id": "cts.skew_bound", "value": 0.12},
        ],
        candidate_id="cts-rerun-001",
    )

    cts_path = workspace.config["CTS"]
    config = _read_json(cts_path)
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    persisted = _read_json(receipt_path)

    assert config["skew_bound"] == 0.12
    assert config["max_fanout"] == 48
    assert config["buffer_type"] == ["BUF_2"]
    assert config["unrelated"] == {"keep": True}
    assert receipt == persisted
    assert receipt["schema"] == "ecc.workspace.candidate_materialization.v1"
    assert receipt["schema_version"] == 1
    assert receipt["candidate_id"] == "cts-rerun-001"
    assert receipt["target_step"] == "CTS"
    assert receipt["target"] == {"step": "CTS"}
    assert receipt["patch"] == [
        {"knob_id": "cts.buffer_type", "value": ["BUF_2"]},
        {"knob_id": "cts.max_fanout", "value": 48},
        {"knob_id": "cts.skew_bound", "value": 0.12},
    ]
    assert receipt["registry_sha256"].startswith("sha256:")
    assert receipt["patch_sha256"].startswith("sha256:")
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert receipt["configs"] == [
        {
            "config_key": "CTS",
            "ref": "config/cts_default_config.json",
            "before_sha256": ANY,
            "after_sha256": _sha256(cts_path),
        }
    ]


def test_materialize_legalization_overlay_targets_real_dreamplace_config(tmp_path):
    workspace = _workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "legalization",
        [
            {"knob_id": "legalization.bndry_padding_x", "value": 4},
            {"knob_id": "legalization.detailed_place_flag", "value": True},
        ],
        candidate_id="legalization-candidate",
    )

    config = _read_json(workspace.config["dreamplace"])
    assert config["bndry_padding_x"] == 4
    assert config["detailed_place_flag"] == 1
    assert receipt["configs"][0]["config_key"] == "dreamplace"
    assert receipt["configs"][0]["ref"] == "config/dreamplace.json"


@pytest.mark.parametrize(
    ("target_step", "patch", "config_key", "path", "reset_value", "expected"),
    [
        (
            "CTS",
            [{"knob_id": "cts.buffer_type", "value": ["BUF_2"]}],
            "CTS",
            ("buffer_type",),
            ["BUF_1"],
            ["BUF_2"],
        ),
        (
            "legalization",
            [{"knob_id": "legalization.bndry_padding_y", "value": 4}],
            "dreamplace",
            ("bndry_padding_y",),
            0,
            4,
        ),
    ],
)
def test_reapply_after_refresh_restores_only_matching_target_and_updates_hashes(
    tmp_path,
    target_step,
    patch,
    config_key,
    path,
    reset_value,
    expected,
):
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        target_step,
        patch,
        candidate_id=f"{target_step}-candidate",
    )

    config_path = workspace.config[config_key]
    refreshed_config = _read_json(config_path)
    current = refreshed_config
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = reset_value
    _write_json(config_path, refreshed_config)

    assert reapply_materialized_candidate_config(workspace, "route") is None
    unchanged = _read_json(config_path)
    current = unchanged
    for key in path:
        current = current[key]
    assert current == reset_value

    receipt = reapply_materialized_candidate_config(workspace, target_step)

    restored = _read_json(config_path)
    current = restored
    for key in path:
        current = current[key]
    assert current == expected
    assert receipt["configs"][0]["after_sha256"] == _sha256(config_path)
    assert receipt["configs"][0]["before_sha256"] != receipt["configs"][0]["after_sha256"]


@pytest.mark.parametrize(
    "target_step,patch",
    [
        ("CTS", [{"knob_id": "legalization.bndry_padding_x", "value": 20000}]),
        ("CTS", [{"knob_id": "cts.max_fanout", "value": True}]),
        ("CTS", [{"knob_id": "cts.buffer_type", "value": ["NOT_A_PDK_BUFFER"]}]),
        ("filler", [{"knob_id": "filler.min_filler_width", "value": 2}]),
        ("place", [{"knob_id": "place.timing_opt", "value": True}]),
        ("CTS", [{"knob_id": "cts.skew_bound", "value": 0.1, "extra": "reject"}]),
    ],
)
def test_materialize_rejects_out_of_contract_patches(tmp_path, target_step, patch):
    workspace = _workspace(tmp_path)

    with pytest.raises(CandidateMaterializationError):
        materialize_candidate_config(
            workspace,
            target_step,
            patch,
            candidate_id="invalid-candidate",
        )


@pytest.mark.parametrize("candidate_id", ["", "bad id", "../candidate"])
def test_materialize_rejects_invalid_candidate_id(tmp_path, candidate_id):
    workspace = _workspace(tmp_path)

    with pytest.raises(CandidateMaterializationError):
        materialize_candidate_config(
            workspace,
            "CTS",
            [{"knob_id": "cts.skew_bound", "value": 0.1}],
            candidate_id=candidate_id,
        )


def test_export_capabilities_writes_stable_schema_and_backend_truth(tmp_path):
    workspace = _workspace(tmp_path)

    capabilities = export_candidate_capabilities(workspace)

    persisted = _read_json(tmp_path / "analysis" / "candidate_capabilities.v1.json")
    cts = next(item for item in capabilities["targets"] if item["target_step"] == "CTS")
    legalization = next(
        item for item in capabilities["targets"] if item["target_step"] == "legalization"
    )
    filler = next(item for item in capabilities["targets"] if item["target_step"] == "filler")
    floorplan = next(item for item in capabilities["targets"] if item["target_step"] == "Floorplan")

    assert capabilities == persisted
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
    assert any(
        knob["knob_id"] == "legalization.detailed_place_flag" for knob in legalization["knobs"]
    )
    assert filler["backend"]["available"] is False
    assert filler["candidate_generation"] is False
    assert filler["knobs"] == []
    assert filler["unavailable_knobs"] == []
    assert "PDN.Grid" in floorplan["excluded_configuration_groups"]
    assert "Floorplan.Auto place pin" in floorplan["excluded_configuration_groups"]


def test_native_legalization_backend_is_fail_closed_for_candidates(tmp_path):
    workspace = _workspace(tmp_path)
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
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "legalization",
        [{"knob_id": "legalization.bndry_padding_x", "value": 4}],
        candidate_id="legalization-candidate",
    )
    legalization = next(
        step for step in workspace.flow.data["steps"] if step["name"] == "legalization"
    )
    legalization["tool"] = "ecc"

    with pytest.raises(CandidateMaterializationError, match="not candidate-capable"):
        validate_materialized_candidate_config(workspace, "legalization")


def test_duplicate_workspace_target_is_fail_closed_for_candidates(tmp_path):
    workspace = _workspace(tmp_path)
    workspace.flow.data["steps"].append({"name": "legalization", "tool": "dreamplace"})

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
