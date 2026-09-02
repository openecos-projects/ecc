import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from agent.data.candidate_artifacts import canonical_json_bytes, sha256_bytes
from agent.data.candidate_capabilities import export_candidate_capabilities
from agent.data.candidate_materialization import (
    CandidateMaterializationError,
    candidate_knob_registry,
    materialize_candidate_config,
    reapply_materialized_candidate_config,
    validate_candidate_materialization_receipt,
    validate_materialized_candidate_config,
)
from agent.data.candidate_registry import candidate_capability_registry


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _rewrite_receipt(path: Path, receipt: dict) -> None:
    receipt["receipt_sha256"] = sha256_bytes(
        canonical_json_bytes(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
    )
    _write_json(path, receipt)


def _workspace(tmp_path: Path):
    tech_path = tmp_path / "pdk" / "tech.lef"
    tech_path.parent.mkdir(parents=True)
    tech_path.write_text(
        "UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\nSITE core7\n  SIZE 0.2 BY 1.4 ;\nEND core7\n",
        encoding="utf-8",
    )
    cts_path = tmp_path / "config" / "cts_ecc.json"
    pl_path = tmp_path / "config" / "filler_ecc.json"
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
        {"-min_filler_width": 1},
    )
    _write_json(
        tmp_path / "config" / "floorplan_ecc.json",
        {"Floorplan": {"Tap distance": 58}},
    )
    _write_json(
        tmp_path / "config" / "dreamplace_ecc.json",
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
        tmp_path / "config" / "route_ecc.json",
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
            "Floorplan": tmp_path / "config" / "floorplan_ecc.json",
            "dreamplace": tmp_path / "config" / "dreamplace_ecc.json",
            "legalization": pl_path,
            "filler": pl_path,
            "route": tmp_path / "config" / "route_ecc.json",
        },
        pdk=SimpleNamespace(
            buffers=["BUF_1", "BUF_2"],
            fillers=["FILL_1", "FILL_2"],
            site_core="core7",
            tech=tech_path,
        ),
        parameters=SimpleNamespace(path=parameters_path),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Floorplan", "tool": "ecc"},
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
        [{"knob_id": "cts.skew_bound", "value": 0.12}],
        candidate_id="cts-rerun-001",
    )

    cts_path = workspace.config["CTS"]
    config = _read_json(cts_path)
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    persisted = _read_json(receipt_path)

    assert config["skew_bound"] == 0.12
    assert config["max_fanout"] == "32"
    assert config["buffer_type"] == ["BUF_1"]
    assert config["unrelated"] == {"keep": True}
    assert receipt == persisted
    assert receipt["schema"] == "ecc.workspace.candidate_materialization.v1"
    assert receipt["schema_version"] == 1
    assert receipt["candidate_id"] == "cts-rerun-001"
    assert receipt["target_step"] == "CTS"
    assert receipt["target"] == {"step": "CTS"}
    assert receipt["patch"] == [{"knob_id": "cts.skew_bound", "value": 0.12}]
    assert receipt["registry_sha256"].startswith("sha256:")
    assert receipt["patch_sha256"].startswith("sha256:")
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert receipt["configs"] == [
        {
            "config_key": "CTS",
            "ref": "config/cts_ecc.json",
            "before_sha256": ANY,
            "after_sha256": _sha256(cts_path),
        }
    ]


def test_materialize_legalization_overlay_targets_real_dreamplace_config(tmp_path):
    workspace = _workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "legalization",
        [{"knob_id": "legalization.detailed_place_flag", "value": True}],
        candidate_id="legalization-candidate",
    )

    config = _read_json(workspace.config["dreamplace"])
    assert config["bndry_padding_x"] == 0
    assert config["detailed_place_flag"] == 1
    assert receipt["configs"][0]["config_key"] == "dreamplace"
    assert receipt["configs"][0]["ref"] == "config/dreamplace_ecc.json"


def test_materialization_preserves_complete_before_and_after_config_snapshots(tmp_path):
    workspace = _workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )

    snapshot = receipt["snapshots"][0]
    before = _read_json(tmp_path / snapshot["before_ref"])
    after = _read_json(tmp_path / snapshot["after_ref"])

    assert snapshot["config_key"] == "dreamplace"
    assert before["target_density"] == 0.8
    assert after["target_density"] == 0.7
    assert snapshot["after_sha256"] == _sha256(workspace.config["dreamplace"])


def test_materialize_rejects_multiple_knobs_without_writing_artifacts(tmp_path):
    workspace = _workspace(tmp_path)
    before = _read_json(workspace.config["CTS"])

    with pytest.raises(CandidateMaterializationError, match="exactly one knob"):
        materialize_candidate_config(
            workspace,
            "CTS",
            [
                {"knob_id": "cts.skew_bound", "value": 0.12},
                {"knob_id": "cts.max_fanout", "value": 48},
            ],
            candidate_id="multi-knob-candidate",
        )

    assert _read_json(workspace.config["CTS"]) == before
    assert not (tmp_path / "analysis" / "candidate_materialization.v1.json").exists()


def test_materialize_rejects_noop_without_writing_artifacts(tmp_path):
    workspace = _workspace(tmp_path)
    before = workspace.config["dreamplace"].read_bytes()

    with pytest.raises(CandidateMaterializationError, match="did not change config"):
        materialize_candidate_config(
            workspace,
            "place",
            [{"knob_id": "place.target_density", "value": 0.8}],
            candidate_id="noop-candidate",
        )

    assert workspace.config["dreamplace"].read_bytes() == before
    assert not (tmp_path / "analysis" / "candidate_materialization.v1.json").exists()
    assert not (tmp_path / "analysis" / "candidate_config_snapshots.v1").exists()


def test_materialize_converts_padding_sites_to_written_dbu(tmp_path):
    workspace = _workspace(tmp_path)

    receipt = materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.cell_padding_x", "value": 2}],
        candidate_id="padding-candidate",
    )

    assert _read_json(workspace.config["dreamplace"])["cell_padding_x"] == 400
    assert receipt["patch"] == [{"knob_id": "place.cell_padding_x", "value": 400}]


def test_receipt_target_mismatch_is_fail_closed(tmp_path):
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )

    with pytest.raises(CandidateMaterializationError, match="target step mismatch"):
        validate_candidate_materialization_receipt(workspace, "route")
    before = _read_json(workspace.config["dreamplace"])

    assert reapply_materialized_candidate_config(workspace, "route") is None
    assert _read_json(workspace.config["dreamplace"]) == before


@pytest.mark.parametrize(
    ("knob_id", "value", "error"),
    [
        ("route.thread_number", 4, "not valid for target step"),
        ("place.target_density", 2.0, "must be <="),
    ],
)
def test_validated_receipt_rechecks_knob_target_and_value(tmp_path, knob_id, value, error):
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = _read_json(receipt_path)
    receipt["patch"] = [{"knob_id": knob_id, "value": value}]
    receipt["patch_sha256"] = sha256_bytes(canonical_json_bytes(receipt["patch"]))
    _rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError, match=error):
        validate_candidate_materialization_receipt(workspace, "place")


def test_validated_receipt_requires_the_registry_config_path(tmp_path):
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = _read_json(receipt_path)
    alternate = tmp_path / "config" / "alternate.json"
    alternate.write_bytes(workspace.config["dreamplace"].read_bytes())
    receipt["configs"][0]["ref"] = "config/alternate.json"
    _rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError, match="config ref does not match registry"):
        validate_candidate_materialization_receipt(workspace, "place")


@pytest.mark.parametrize(
    "tamper",
    ["snapshot_key", "incomplete_hash", "before_hash_mismatch", "missing_snapshots"],
)
def test_validated_receipt_requires_complete_one_to_one_config_snapshots(tmp_path, tamper):
    workspace = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = _read_json(receipt_path)
    if tamper == "snapshot_key":
        receipt["snapshots"][0]["config_key"] = "CTS"
    elif tamper == "incomplete_hash":
        receipt["configs"][0]["before_sha256"] = "sha256:x"
    elif tamper == "before_hash_mismatch":
        receipt["snapshots"][0]["before_sha256"] = "sha256:" + "a" * 64
    else:
        receipt["snapshots"] = []
    _rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError):
        validate_candidate_materialization_receipt(workspace, "place")


def test_reapply_keeps_in_memory_parameters_consistent(tmp_path):
    workspace = _workspace(tmp_path)
    workspace.parameters.data = _read_json(workspace.parameters.path)
    materialize_candidate_config(
        workspace,
        "Floorplan",
        [{"knob_id": "floorplan.core_util", "value": 0.7}],
        candidate_id="floorplan-candidate",
    )
    refreshed = _read_json(workspace.parameters.path)
    refreshed["Core"]["Utilitization"] = 0.6
    _write_json(workspace.parameters.path, refreshed)
    workspace.parameters.data = refreshed

    reapply_materialized_candidate_config(workspace, "Floorplan")

    assert workspace.parameters.data == _read_json(workspace.parameters.path)
    assert workspace.parameters.data["Core"]["Utilitization"] == 0.7


def test_reapply_keeps_receipt_when_tool_rewrites_equivalent_json(tmp_path):
    workspace = _workspace(tmp_path)
    original = materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.6}],
        candidate_id="equivalent-json-candidate",
    )
    config_path = workspace.config["dreamplace"]
    config_path.write_text(json.dumps(_read_json(config_path), indent=4) + "\n", encoding="utf-8")

    reapplied = reapply_materialized_candidate_config(workspace, "place")

    assert reapplied["receipt_sha256"] == original["receipt_sha256"]
    assert reapplied["snapshots"] == original["snapshots"]


def test_reapply_keeps_original_receipt_when_config_is_already_materialized(tmp_path):
    workspace = _workspace(tmp_path)
    original = materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )

    reapplied = reapply_materialized_candidate_config(workspace, "place")

    assert reapplied == original
    assert reapplied["configs"][0]["before_sha256"] != reapplied["configs"][0]["after_sha256"]


def test_materialized_candidate_rejects_tampered_config_snapshot(tmp_path):
    workspace = _workspace(tmp_path)
    receipt = materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    (tmp_path / receipt["snapshots"][0]["after_ref"]).write_text("{}\n", encoding="utf-8")

    with pytest.raises(CandidateMaterializationError, match="config snapshot drift"):
        validate_materialized_candidate_config(workspace, "place")


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
