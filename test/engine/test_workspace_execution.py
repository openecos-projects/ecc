import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.data.workspace import Workspace
from chipcompiler.data.workspace.execution import declared_step_subprocess, save_step_subprocess
from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
from chipcompiler.engine.flow.runner import EngineFlow
from chipcompiler.engine.snapshot.store import read_engineering_snapshot
from chipcompiler.engine.step.process import execution_mode, is_enabled
from chipcompiler.engine.workspace.derive import derive_workspace
from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
from chipcompiler.engine.workspace_execution import update_workspace_execution


@pytest.fixture
def execution_workspace(tmp_path, minimal_ics55_pdk_factory):
    root = Path(__file__).parents[1] / "fixtures" / "workspace_spec"
    payload = json.loads((root / "valid.json").read_text())
    spec, bindings = payload["workspaceSpec"], payload["workspaceBindings"]
    bindings["inputs"] = {key: str(root / value) for key, value in bindings["inputs"].items()}
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    spec["flow"]["stepSubprocess"] = False
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)
    return workspace, spec, bindings


def test_workspace_execution_mode_is_local_and_environment_is_a_temporary_override(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ECC_STEP_SUBPROCESS", raising=False)
    first, second = (
        Workspace(directory=tmp_path / "first"),
        Workspace(directory=tmp_path / "second"),
    )
    first.flow.data["options"] = {"execution": {"step_subprocess": False}}
    assert (execution_mode(first), execution_mode(second)) == (
        (False, "home/flow.json"),
        (True, "default"),
    )
    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "1")
    assert execution_mode(first) == (True, "ECC_STEP_SUBPROCESS")
    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "0")
    assert not is_enabled(second)
    assert declared_step_subprocess(first.flow.data) is False
    monkeypatch.delenv("ECC_STEP_SUBPROCESS")
    assert not is_enabled(first)
    assert "ECC_STEP_SUBPROCESS" not in os.environ


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_invalid_persisted_execution_values_are_rejected(value):
    with pytest.raises(ValueError, match="must be a boolean"):
        declared_step_subprocess({"options": {"execution": {"step_subprocess": value}}})


def test_serial_workspace_disables_checker_batch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("ECC_STEP_SUBPROCESS", raising=False)
    workspace = Workspace(directory=tmp_path)
    flow = EngineFlow(workspace)
    workspace.flow.data = {
        "steps": [{"name": "lvs", "tool": "ecc", "state": "Unstart", "category": "CHECKER"}],
        "options": {"execution": {"step_subprocess": False}},
    }
    step = SimpleNamespace(name="lvs", tool="ecc")
    flow.workspace_steps = [SimpleNamespace(name="filler"), step]
    assert not flow._can_parallelize_checker_batch(step, 1, None)
    workspace.flow.data["options"]["execution"]["step_subprocess"] = True
    assert flow._can_parallelize_checker_batch(step, 1, None)


def test_execution_setting_is_ledger_owned_and_update_preserves_results(execution_workspace):
    workspace, _spec, _bindings = execution_workspace
    flow_path = workspace.directory / "home" / "flow.json"
    params_path = workspace.directory / "home" / "params.toml"
    params_before = params_path.read_bytes()
    for step in workspace.flow.data["steps"]:
        step["state"] = "Success"
    workspace.flow.data["options"]["future"] = {"keep": 7}
    save_step_subprocess(workspace.flow, value=False)
    before = json.loads(flow_path.read_bytes())
    initial = read_engineering_snapshot(workspace)
    assert initial["workspaceSpec"]["flow"]["stepSubprocess"] is False
    updated = update_workspace_execution(
        workspace.directory, step_subprocess=True, expected_revision=1, command_id="execution-1"
    )
    expected = deepcopy(before)
    expected["options"]["execution"]["step_subprocess"] = True
    assert json.loads(flow_path.read_bytes()) == expected
    assert params_path.read_bytes() == params_before
    snapshot = read_engineering_snapshot(updated)
    assert (snapshot["workspaceRevision"], snapshot["workspaceSpec"]["flow"]["stepSubprocess"]) == (
        2,
        True,
    )
    assert snapshot["flow"] == expected
    retry = update_workspace_execution(
        workspace.directory, step_subprocess=True, expected_revision=1, command_id="execution-1"
    )
    assert read_engineering_snapshot(retry) == snapshot
    with pytest.raises(WorkspaceLifecycleError, match="Revision"):
        update_workspace_execution(workspace.directory, step_subprocess=False, expected_revision=1)
    with pytest.raises(WorkspaceLifecycleError) as conflict:
        update_workspace_execution(
            workspace.directory,
            step_subprocess=False,
            expected_revision=1,
            command_id="execution-1",
        )
    assert conflict.value.code == "idempotency_conflict"
    assert json.loads(flow_path.read_bytes()) == expected


def test_execution_update_rolls_back_when_snapshot_publication_fails(
    execution_workspace, monkeypatch
):
    workspace, _spec, _bindings = execution_workspace
    home = workspace.directory / "home"
    before = {path.name: path.read_bytes() for path in home.iterdir() if path.is_file()}

    def fail(*_args, **_kwargs):
        raise OSError("snapshot write failed")

    monkeypatch.setattr(
        "chipcompiler.engine.workspace_execution.refresh_engineering_snapshot", fail
    )
    with pytest.raises(OSError, match="snapshot write failed"):
        update_workspace_execution(
            workspace.directory, step_subprocess=True, command_id="execution-1"
        )
    assert {path.name: path.read_bytes() for path in home.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("interrupted_after", ["flow", "snapshot", "command"])
def test_execution_update_recovers_interrupted_transaction_before_reading_state(
    execution_workspace, interrupted_after
):
    from chipcompiler.data.workspace.transaction import WorkspaceFileTransaction
    from chipcompiler.engine.snapshot.store import refresh_engineering_snapshot
    from chipcompiler.engine.workspace.lifecycle import (
        workspace_command_fingerprint,
        write_workspace_command,
    )

    workspace, _spec, _bindings = execution_workspace
    home = workspace.directory / "home"
    workspace_id = read_engineering_snapshot(workspace)["workspaceId"]
    transaction = WorkspaceFileTransaction.begin(
        workspace.directory,
        [
            home / name
            for name in ("flow.json", "engineering-snapshot.json", "workspace-commands.json")
        ],
    )
    save_step_subprocess(workspace.flow, value=True)
    if interrupted_after != "flow":
        snapshot = refresh_engineering_snapshot(
            workspace, workspace_id=workspace_id, cause="workspace.execution_updated"
        )
        if interrupted_after == "command":
            write_workspace_command(
                workspace.directory,
                "interrupted-execution",
                workspace_command_fingerprint("execution", {"stepSubprocess": True}, None, 1),
                snapshot["workspaceId"],
                snapshot["workspaceRevision"],
            )
    # A terminated writer releases its locks while leaving the recovery journal.
    transaction._release()

    updated = update_workspace_execution(
        workspace.directory,
        step_subprocess=True,
        expected_revision=1,
        command_id="interrupted-execution",
    )
    assert declared_step_subprocess(json.loads((home / "flow.json").read_text())) is True
    assert read_engineering_snapshot(updated)["workspaceRevision"] == 2
    assert not transaction.backup.exists()


def test_execution_update_no_wait_leaves_busy_workspace_unchanged(execution_workspace):
    fcntl = pytest.importorskip("fcntl")
    workspace, _spec, _bindings = execution_workspace
    flow_path = workspace.directory / "home" / "flow.json"
    before = flow_path.read_bytes()
    with Path(f"{workspace.directory}.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            update_workspace_execution(workspace.directory, step_subprocess=True, blocking=False)
    assert flow_path.read_bytes() == before


def test_execution_ledger_write_failure_restores_memory(execution_workspace, monkeypatch):
    workspace, _spec, _bindings = execution_workspace
    before = deepcopy(workspace.flow.data)
    monkeypatch.setattr("chipcompiler.data.workspace.execution.save_ledger", lambda _flow: False)
    with pytest.raises(OSError, match="persist workspace execution"):
        save_step_subprocess(workspace.flow, value=True)
    assert workspace.flow.data == before


def test_refresh_and_derive_preserve_or_override_execution_choice(execution_workspace, tmp_path):
    workspace, spec, bindings = execution_workspace
    spec["flow"].pop("stepSubprocess")
    refreshed = update_workspace_from_spec(workspace.directory, 1, spec, bindings)
    assert declared_step_subprocess(refreshed.workspace.flow.data) is False
    spec["flow"]["stepSubprocess"] = True
    refreshed = update_workspace_from_spec(workspace.directory, 2, spec, bindings)
    assert declared_step_subprocess(refreshed.workspace.flow.data) is True
    inherited = derive_workspace(workspace.directory, tmp_path / "inherited")
    overridden = derive_workspace(
        workspace.directory, tmp_path / "overridden", step_subprocess=False
    )
    assert declared_step_subprocess(inherited.flow.data) is True
    assert declared_step_subprocess(overridden.flow.data) is False
    assert declared_step_subprocess(refreshed.workspace.flow.data) is True


def test_invalid_spec_execution_does_not_create_workspace(execution_workspace, tmp_path):
    _workspace, spec, bindings = execution_workspace
    spec["flow"]["stepSubprocess"] = "false"
    with pytest.raises(WorkspaceLifecycleError) as error:
        create_workspace_from_spec(tmp_path / "invalid", spec, bindings)
    assert error.value.code == "workspace_spec_invalid"
    assert not (tmp_path / "invalid").exists()
