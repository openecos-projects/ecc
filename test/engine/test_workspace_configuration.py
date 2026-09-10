import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.data import load_workspace
from chipcompiler.engine import (
    EngineFlow,
    WorkspaceLifecycleError,
    create_workspace_from_spec,
    read_step_configuration,
    read_workspace_configuration_from_directory,
    update_workspace_configuration,
    update_workspace_step_configuration,
)
from chipcompiler.engine.snapshot import create_engineering_snapshot, read_engineering_snapshot


def _workspace_spec_fixture() -> tuple[dict, dict]:
    root = Path(__file__).parents[1] / "fixtures" / "workspace_spec"
    payload = json.loads((root / "valid.json").read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {key: str(root / value) for key, value in bindings["inputs"].items()}
    return payload["workspaceSpec"], bindings


def test_workspace_configuration_update_is_revision_aware_and_idempotent(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    initial = read_engineering_snapshot(workspace)

    updated = update_workspace_configuration(
        workspace.directory,
        initial["workspaceRevision"],
        {"parameters": {"design.frequency_mhz": 250.0}},
        bindings,
        "configuration-1",
    )
    current = read_engineering_snapshot(updated)
    repeated = update_workspace_configuration(
        workspace.directory,
        initial["workspaceRevision"],
        {"parameters": {"design.frequency_mhz": 250.0}},
        bindings,
        "configuration-1",
    )

    assert initial["workspaceRevision"] == 1
    assert current["workspaceRevision"] == 2
    assert read_engineering_snapshot(repeated)["workspaceRevision"] == 2
    assert repeated.parameters.data["frequency_max"] == 250.0
    assert (
        read_workspace_configuration_from_directory(workspace.directory)["workspaceSpec"][
            "parameters"
        ]["design.frequency_mhz"]
        == 250.0
    )

    with pytest.raises(WorkspaceLifecycleError) as conflict:
        update_workspace_configuration(
            workspace.directory,
            1,
            {"parameters": {"design.frequency_mhz": 300.0}},
            bindings,
            "configuration-2",
        )
    assert conflict.value.code == "revision_conflict"
    assert read_engineering_snapshot(updated)["workspaceRevision"] == 2


def test_workspace_configuration_update_rolls_back_refresh_failure(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    before_config = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = read_engineering_snapshot(workspace)

    def fail_refresh(_workspace):
        raise RuntimeError("config regeneration failed")

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", fail_refresh)
    with pytest.raises(RuntimeError, match="config regeneration failed"):
        update_workspace_configuration(
            workspace.directory,
            before_snapshot["workspaceRevision"],
            {"parameters": {"design.frequency_mhz": 250.0}},
            bindings,
            "configuration-1",
        )

    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_config
    assert read_engineering_snapshot(workspace) == before_snapshot


def test_configuration_update_recovers_after_process_exit_before_snapshot(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    before = read_engineering_snapshot(workspace)

    child = os.fork()
    if child == 0:
        import chipcompiler.engine.workspace_configuration as configuration_module

        configuration_module.invalidate_engineering_snapshot = lambda *_args, **_kwargs: os._exit(
            23
        )
        update_workspace_configuration(
            workspace.directory,
            before["workspaceRevision"],
            {"parameters": {"design.frequency_mhz": 250.0}},
            bindings,
            "configuration-crash",
        )
        os._exit(99)

    _pid, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 23

    updated = update_workspace_configuration(
        workspace.directory,
        before["workspaceRevision"],
        {"parameters": {"design.frequency_mhz": 250.0}},
        bindings,
        "configuration-crash",
    )

    assert updated.parameters.data["frequency_max"] == 250.0
    assert read_engineering_snapshot(updated)["workspaceRevision"] == (
        before["workspaceRevision"] + 1
    )


def test_configuration_update_recovers_after_process_exit_during_commit_cleanup(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    before = read_engineering_snapshot(workspace)

    child = os.fork()
    if child == 0:
        import chipcompiler.data.workspace_transaction as transaction_module

        original_rmtree = transaction_module.shutil.rmtree

        def crash_cleanup(path, *args, **kwargs):
            if Path(path).name == ".workspace-configuration-backup.discard":
                os._exit(24)
            return original_rmtree(path, *args, **kwargs)

        transaction_module.shutil.rmtree = crash_cleanup
        update_workspace_configuration(
            workspace.directory,
            before["workspaceRevision"],
            {"parameters": {"design.frequency_mhz": 250.0}},
            bindings,
            "configuration-cleanup-crash",
        )
        os._exit(99)

    _pid, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 24

    recovered = load_workspace(workspace.directory)
    assert recovered.parameters.data["frequency_max"] == 250.0
    assert read_engineering_snapshot(recovered)["workspaceRevision"] == (
        before["workspaceRevision"] + 1
    )


def test_read_workspace_configuration_does_not_materialize_missing_home_files(
    tmp_path, minimal_ics55_pdk_factory
):
    import shutil

    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)
    home_file = workspace.directory / "home" / "home.json"
    checklist_file = workspace.directory / "home" / "checklist.json"
    log_dir = workspace.directory / "log"
    home_file.unlink()
    checklist_file.unlink()
    if log_dir.exists():
        shutil.rmtree(log_dir)
    shutil.rmtree(Path(bindings["pdk"]["root"]))

    configuration = read_workspace_configuration_from_directory(workspace.directory)
    readonly_workspace = load_workspace(workspace.directory, read_only=True)
    from chipcompiler.tools.ecc.signoff_checklist import rebuild_home_checklist

    rebuild_home_checklist(readonly_workspace, persist=False)

    assert configuration["workspaceSpec"]["pdk"]["familyId"] == "ics55"
    assert not home_file.exists()
    assert not checklist_file.exists()
    assert not log_dir.exists()


def test_step_configuration_update_invalidates_only_target_suffix(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data["steps"][:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )

    configuration = read_step_configuration(workspace, "floor-plan")
    synthesis = read_step_configuration(workspace, "synthesis")
    updated = update_workspace_step_configuration(
        workspace.directory,
        configuration["workspaceRevision"],
        "Floorplan",
        {"floorplan.core_util": 0.55},
        "step-configuration-1",
    )

    records = {record["param"]: record for record in configuration["parameters"]}
    synthesis_params = {record["param"] for record in synthesis["parameters"]}
    assert {"design.frequency_mhz", "flow.run_analysis"} <= synthesis_params
    assert "floorplan.core_util" in records
    assert set(records["floorplan.core_util"]) == {
        "param",
        "type",
        "value",
        "default",
        "applies",
        "description",
        "range",
    }
    states = {step["name"]: step["state"] for step in updated.flow.steps()}
    assert states["Synthesis"] == "Success"
    assert states["lec"] == "Success"
    assert states["Floorplan"] == "Unstart"
    assert read_engineering_snapshot(updated)["workspaceRevision"] == 2

    with pytest.raises(WorkspaceLifecycleError) as inapplicable:
        update_workspace_step_configuration(
            workspace.directory,
            2,
            "Floorplan",
            {"place.target_density": 0.6},
            "step-configuration-2",
        )
    assert inapplicable.value.code == "parameter_not_applicable"
    assert read_engineering_snapshot(updated)["workspaceRevision"] == 2
