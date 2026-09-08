import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.engine import (
    WorkspaceLifecycleError,
    create_workspace_from_spec,
    read_workspace_configuration_from_directory,
    update_workspace_configuration,
)
from chipcompiler.engine.snapshot import read_engineering_snapshot


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
