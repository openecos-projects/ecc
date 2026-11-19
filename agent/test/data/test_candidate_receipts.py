"""Materialization receipts: validation, tampering and reapply after a refresh."""

import json

import pytest

from agent.data.candidate_artifacts import canonical_json_bytes, sha256_bytes
from agent.data.candidate_materialization import (
    CandidateMaterializationError,
    materialize_candidate_config,
    reapply_materialized_candidate_config,
    validate_candidate_materialization_receipt,
    validate_materialized_candidate_config,
)
from agent.test.data import candidate_workspace as cw


def test_receipt_target_mismatch_is_fail_closed(tmp_path):
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )

    with pytest.raises(CandidateMaterializationError, match="target step mismatch"):
        validate_candidate_materialization_receipt(workspace, "routing")
    before = cw.read_json(workspace.config["dreamplace"])

    assert reapply_materialized_candidate_config(workspace, "routing") is None
    assert cw.read_json(workspace.config["dreamplace"]) == before


@pytest.mark.parametrize(
    ("knob_id", "value", "error"),
    [
        ("route.thread_number", 4, "not valid for target step"),
        ("place.target_density", 2.0, "must be <="),
    ],
)
def test_validated_receipt_rechecks_knob_target_and_value(tmp_path, knob_id, value, error):
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = cw.read_json(receipt_path)
    receipt["patch"] = [{"knob_id": knob_id, "value": value}]
    receipt["patch_sha256"] = sha256_bytes(canonical_json_bytes(receipt["patch"]))
    cw.rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError, match=error):
        validate_candidate_materialization_receipt(workspace, "placement")


def test_validated_receipt_requires_the_registry_config_path(tmp_path):
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = cw.read_json(receipt_path)
    alternate = tmp_path / "config" / "alternate.json"
    alternate.write_bytes(workspace.config["dreamplace"].read_bytes())
    receipt["configs"][0]["ref"] = "config/alternate.json"
    cw.rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError, match="config ref does not match registry"):
        validate_candidate_materialization_receipt(workspace, "placement")


@pytest.mark.parametrize(
    "tamper",
    ["snapshot_key", "incomplete_hash", "before_hash_mismatch", "missing_snapshots"],
)
def test_validated_receipt_requires_complete_one_to_one_config_snapshots(tmp_path, tamper):
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    receipt_path = tmp_path / "analysis" / "candidate_materialization.v1.json"
    receipt = cw.read_json(receipt_path)
    if tamper == "snapshot_key":
        receipt["snapshots"][0]["config_key"] = "cts"
    elif tamper == "incomplete_hash":
        receipt["configs"][0]["before_sha256"] = "sha256:x"
    elif tamper == "before_hash_mismatch":
        receipt["snapshots"][0]["before_sha256"] = "sha256:" + "a" * 64
    else:
        receipt["snapshots"] = []
    cw.rewrite_receipt(receipt_path, receipt)

    with pytest.raises(CandidateMaterializationError):
        validate_candidate_materialization_receipt(workspace, "placement")


def test_reapply_keeps_in_memory_parameters_consistent(tmp_path):
    from chipcompiler.data.parameter import load_parameter, save_parameter

    workspace = cw.workspace(tmp_path)
    workspace.parameters.data = load_parameter(workspace.parameters.path).data
    materialize_candidate_config(
        workspace,
        "floorplan",
        [{"knob_id": "floorplan.core_util", "value": 0.7}],
        candidate_id="floorplan-candidate",
    )
    refreshed = load_parameter(workspace.parameters.path)
    refreshed.data["core"]["utilitization"] = 0.6
    assert save_parameter(refreshed)
    workspace.parameters.data = refreshed.data

    reapply_materialized_candidate_config(workspace, "floorplan")

    assert workspace.parameters.data == load_parameter(workspace.parameters.path).data
    assert workspace.parameters.data["core"]["utilitization"] == 0.7


def test_reapply_keeps_receipt_when_tool_rewrites_equivalent_json(tmp_path):
    workspace = cw.workspace(tmp_path)
    original = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.6}],
        candidate_id="equivalent-json-candidate",
    )
    config_path = workspace.config["dreamplace"]
    config_path.write_text(json.dumps(cw.read_json(config_path), indent=4) + "\n", encoding="utf-8")

    reapplied = reapply_materialized_candidate_config(workspace, "placement")

    assert reapplied is not None
    assert reapplied["receipt_sha256"] == original["receipt_sha256"]
    assert reapplied["snapshots"] == original["snapshots"]


def test_reapply_keeps_original_receipt_when_config_is_already_materialized(tmp_path):
    workspace = cw.workspace(tmp_path)
    original = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )

    reapplied = reapply_materialized_candidate_config(workspace, "placement")

    assert reapplied is not None
    assert reapplied == original
    assert reapplied["configs"][0]["before_sha256"] != reapplied["configs"][0]["after_sha256"]


def test_materialized_candidate_rejects_tampered_config_snapshot(tmp_path):
    workspace = cw.workspace(tmp_path)
    receipt = materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.7}],
        candidate_id="place-candidate",
    )
    (tmp_path / receipt["snapshots"][0]["after_ref"]).write_text("{}\n", encoding="utf-8")

    with pytest.raises(CandidateMaterializationError, match="config snapshot drift"):
        validate_materialized_candidate_config(workspace, "placement")


@pytest.mark.parametrize(
    ("target_step", "patch", "config_key", "path", "reset_value", "expected"),
    [
        (
            "cts",
            [{"knob_id": "cts.buffer_type", "value": ["BUF_2"]}],
            "cts",
            ("buffer_type",),
            ["BUF_1"],
            ["BUF_2"],
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
    workspace = cw.workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        target_step,
        patch,
        candidate_id=f"{target_step}-candidate",
    )

    config_path = workspace.config[config_key]
    refreshed_config = cw.read_json(config_path)
    current = refreshed_config
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = reset_value
    cw.write_json(config_path, refreshed_config)

    assert reapply_materialized_candidate_config(workspace, "routing") is None
    unchanged = cw.read_json(config_path)
    current = unchanged
    for key in path:
        current = current[key]
    assert current == reset_value

    receipt = reapply_materialized_candidate_config(workspace, target_step)

    assert receipt is not None
    restored = cw.read_json(config_path)
    assert restored is not None
    current = restored
    for key in path:
        current = current[key]
    assert current == expected
    assert receipt["configs"][0]["after_sha256"] == cw.sha256(config_path)
    assert receipt["configs"][0]["before_sha256"] != receipt["configs"][0]["after_sha256"]
