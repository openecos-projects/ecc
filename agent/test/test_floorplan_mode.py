import json
import shutil
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.floorplan_mode import (
    FLOORPLAN_MODE_REF,
    apply_floorplan_mode,
    prepare_floorplan_mode,
    read_floorplan_mode,
)
from agent.requests import CandidateRerunRequest, parse_agent_request_model
from agent.workspace_api import _validate_candidate_rerun_request
from chipcompiler.runtime.workspace_api import RuntimeApiError


def _request(**kwargs):
    return CandidateRerunRequest(
        **{
            "workspace_id": "workspace-1",
            "candidate_id": "candidate-1",
            "target_step": "Floorplan",
            "end_step": "Harden",
            "execution_scope": "full_flow",
            "idempotency_key": "mode-1",
            "context_sha256": "sha256:" + "a" * 64,
            "parameter_card_sha256": "sha256:" + "b" * 64,
            "seed": 17,
            "patch": [],
            "floorplan_mode": "die_util",
            **kwargs,
        }
    )


def _workspace(tmp_path):
    root = tmp_path / ".agent" / "candidates" / "candidate-1"
    config = root / "config" / "floorplan_ecc.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "die_builder": {
                    "mode": "die_size",
                    "die_size": {"width_micron": 100, "height_micron": 200},
                    "die_util": {"utilization": 0.5, "aspect_ratio": 1.0},
                }
            }
        )
    )
    return SimpleNamespace(directory=root, config={"Floorplan": config})


@pytest.mark.parametrize("mode", ("die_util", "die_size"))
def test_explicit_mode_only_baseline_request(mode):
    request = _request(floorplan_mode=mode)
    _validate_candidate_rerun_request(request)
    payload = dict(vars(request))
    payload["floorplanMode"] = payload.pop("floorplan_mode")
    assert parse_agent_request_model(CandidateRerunRequest, payload) == request


@pytest.mark.parametrize(
    "overrides",
    (
        {"floorplan_mode": "auto"},
        {"floorplan_mode": False},
        {"floorplan_mode": None},
        {"target_step": "place"},
    ),
)
def test_invalid_mode_request_is_rejected_before_execution(overrides):
    with pytest.raises(RuntimeApiError):
        _validate_candidate_rerun_request(_request(**overrides))


@pytest.mark.parametrize("mode", ("die_util", "die_size"))
def test_mode_is_reapplied_after_config_rebuild_and_reload(tmp_path, mode):
    workspace = _workspace(tmp_path)
    prepare_floorplan_mode(workspace, _request(floorplan_mode=mode))
    config = workspace.config["Floorplan"]
    rebuilt = json.loads(config.read_text())
    rebuilt["die_builder"]["mode"] = "die_size" if mode == "die_util" else "die_util"
    config.write_text(json.dumps(rebuilt))
    reloaded = SimpleNamespace(directory=workspace.directory, config=workspace.config)
    apply_floorplan_mode(reloaded, "Floorplan")
    assert json.loads(config.read_text())["die_builder"] == {
        "mode": mode,
        "die_size": {"width_micron": 100, "height_micron": 200},
        "die_util": {"utilization": 0.5, "aspect_ratio": 1.0},
    }
    receipt = read_floorplan_mode(reloaded)
    assert receipt["mode"] == mode
    assert receipt["previous_mode"] == "die_size"


def test_mode_tampering_and_nonisolated_workspace_fail_closed(tmp_path):
    workspace = _workspace(tmp_path)
    prepare_floorplan_mode(workspace, _request())
    path = workspace.directory / FLOORPLAN_MODE_REF
    receipt = json.loads(path.read_text())
    receipt["mode"] = "die_size"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="hash"):
        apply_floorplan_mode(workspace, "Floorplan")
    ordinary = SimpleNamespace(directory=tmp_path, config=workspace.config)
    with pytest.raises(ValueError, match="isolated"):
        prepare_floorplan_mode(ordinary, _request())


def test_missing_mode_leaves_ordinary_workspace_unchanged(tmp_path):
    ordinary = SimpleNamespace(directory=tmp_path, config={})
    prepare_floorplan_mode(ordinary, replace(_request(), floorplan_mode=None))
    apply_floorplan_mode(ordinary, "Floorplan")
    assert list(tmp_path.iterdir()) == []


def test_mode_state_hash_binds_canonical_parameters_and_resume_rolls_back(tmp_path):
    from agent.candidate_resume import (
        _candidate_resume_config_backups,
        _restore_candidate_resume_configs,
    )
    from agent.workspace_api import _workspace_state_sha256
    from chipcompiler.data.parameter import load_parameter

    workspace = _workspace(tmp_path)
    home = workspace.directory / "home"
    home.mkdir()
    params = home / "params.toml"
    params.write_text("[params.core]\nutilitization = 0.4\n")
    workspace.parameters = load_parameter(params)
    prepare_floorplan_mode(workspace, _request())
    digest = _workspace_state_sha256(workspace.directory)
    backups = _candidate_resume_config_backups(workspace)
    params.write_text("[params.core]\nutilitization = 0.7\n")
    assert _workspace_state_sha256(workspace.directory) != digest
    _restore_candidate_resume_configs(workspace, backups)
    assert _workspace_state_sha256(workspace.directory) == digest
    assert workspace.parameters.data["core"]["utilitization"] == 0.4


def test_terminal_success_rejects_a_lost_mode_override(tmp_path):
    from agent.floorplan_mode import validate_floorplan_mode_result

    workspace = _workspace(tmp_path)
    prepare_floorplan_mode(workspace, _request())
    config = workspace.config["Floorplan"]
    payload = json.loads(config.read_text())
    payload["die_builder"]["mode"] = "die_size"
    config.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="terminal floorplan mode"):
        validate_floorplan_mode_result(workspace, "succeeded")
    validate_floorplan_mode_result(workspace, "failed")


def test_mode_inheritance_switchback_and_context_binding(tmp_path):
    from agent.floorplan_mode import validate_floorplan_mode_resume

    first = _workspace(tmp_path)
    prepare_floorplan_mode(first, _request())
    before = {
        p.relative_to(first.directory): p.read_bytes()
        for p in first.directory.rglob("*")
        if p.is_file()
    }
    second_root = first.directory.with_name("candidate-2")
    shutil.copytree(first.directory, second_root)
    second = SimpleNamespace(
        directory=second_root, config={"Floorplan": second_root / "config/floorplan_ecc.json"}
    )
    request = _request(
        candidate_id="candidate-2",
        floorplan_mode=None,
        patch=[{"knob_id": "floorplan.core_util", "value": 0.7}],
    )
    prepare_floorplan_mode(second, request)
    assert read_floorplan_mode(second)["mode"] == "die_util"
    assert read_floorplan_mode(second)["candidate_id"] == "candidate-2"
    assert validate_floorplan_mode_resume(second, request)["patch"] == request.patch
    with pytest.raises(ValueError, match="context"):
        validate_floorplan_mode_resume(second, replace(request, seed=18))
    prepare_floorplan_mode(second, replace(request, floorplan_mode="die_size"))
    assert json.loads(second.config["Floorplan"].read_text())["die_builder"]["mode"] == "die_size"
    assert before == {
        p.relative_to(first.directory): p.read_bytes()
        for p in first.directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("width", (0, -1, False, float("nan"), float("inf")))
def test_fixed_size_rejects_invalid_dimensions_without_writing_receipt(tmp_path, width):
    workspace = _workspace(tmp_path)
    config = workspace.config["Floorplan"]
    payload = json.loads(config.read_text())
    payload["die_builder"]["die_size"]["width_micron"] = width
    config.write_text(json.dumps(payload))
    before = config.read_bytes()
    with pytest.raises(ValueError, match="positive"):
        prepare_floorplan_mode(workspace, _request(floorplan_mode="die_size"))
    assert config.read_bytes() == before
    assert not (workspace.directory / FLOORPLAN_MODE_REF).exists()


def test_mode_rejects_config_symlinks(tmp_path):
    workspace = _workspace(tmp_path)
    config = workspace.config["Floorplan"]
    outside = tmp_path / "outside.json"
    config.rename(outside)
    config.symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(ValueError, match="unsafe"):
        prepare_floorplan_mode(workspace, _request())
    assert outside.read_bytes() == before


@pytest.mark.parametrize("mode", ("die_util", "die_size"))
@pytest.mark.parametrize(
    "knob,value,field",
    (
        ("floorplan.core_util", 0.7, "utilization"),
        ("floorplan.aspect_ratio", 2.0, "aspect_ratio"),
    ),
)
def test_parameter_patch_survives_native_refresh_in_selected_mode(
    tmp_path, monkeypatch, mode, knob, value, field
):
    from agent import tools
    from agent.data.candidate_materialization import materialize_candidate_config
    from agent.data.floorplan_parameter_observer import build_floorplan_report
    from agent.test.data.test_candidate_materialization import _workspace as parameter_workspace
    from chipcompiler.data.parameter import load_parameter, save_parameter
    from chipcompiler.data.workspace import _refresh_floorplan_config

    root = tmp_path / ".agent/candidates/candidate-1"
    workspace = parameter_workspace(root)
    workspace.pdk.tap_cell = ""
    workspace.pdk.end_cap = ""
    workspace.parameters = load_parameter(workspace.parameters.path)
    workspace.parameters.data["die"] = {"size": [100, 200]}
    save_parameter(workspace.parameters)
    workspace.logger = SimpleNamespace()
    _refresh_floorplan_config(workspace)
    patch = [{"knob_id": knob, "value": value}]
    prepare_floorplan_mode(workspace, _request(floorplan_mode=mode, patch=patch))
    materialize_candidate_config(workspace, "Floorplan", patch, "candidate-1")
    observed = []

    def builder(workspace, _step):
        workspace.parameters = load_parameter(workspace.parameters.path)
        _refresh_floorplan_config(workspace)
        assert (
            json.loads(workspace.config["Floorplan"].read_text())["die_builder"]["mode"]
            == "die_size"
        )

    def native(**_kwargs):
        observed.append(json.loads(workspace.config["Floorplan"].read_text())["die_builder"])
        return True

    monkeypatch.setattr(
        tools,
        "load_eda_module",
        lambda *_args, **_kwargs: SimpleNamespace(build_step_config=builder, run_step=native),
    )
    monkeypatch.setattr(tools, "log_workspace_step", lambda *_args: None)
    monkeypatch.setattr(
        tools, "run_with_parameter_observation", lambda _ws, _step, _mat, run: run()
    )
    assert tools.run_step(workspace, SimpleNamespace(name="Floorplan", tool="ecc"))
    assert observed[0]["mode"] == mode
    assert observed[0]["die_util"][field] == value
    assert workspace.parameters.data["die"]["size"] == [100, 200]
    feature = root / "feature.json"
    feature.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_usage": 0.69,
                    "core_bounding_width": 40,
                    "core_bounding_height": 20,
                }
            }
        )
    )
    report = build_floorplan_report(
        patch[0],
        {
            "init_fp_call_count": 1,
            "run_fp_call_count": 1,
            "run_fp_completed": True,
            "config_path": str(workspace.config["Floorplan"]),
        },
        feature,
        engine_succeeded=True,
    )
    assert report["status"] == ("effective" if mode == "die_util" else "inactive")
    assert report["actual_value"] == (value if mode == "die_util" else None)
