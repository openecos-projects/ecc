import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.data import load_workspace
from chipcompiler.engine import (
    EngineFlow,
    WorkspaceLifecycleError,
    apply_workspace_parameters,
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


def test_workspace_parameter_batch_commits_once_and_invalidates_from_earliest_step(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    baseline_density = workspace.parameters.data["dreamplace"]["target_density"]
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", []):
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )

    updated = apply_workspace_parameters(
        workspace.directory,
        1,
        {"place.target_density": 0.65, "cts.skew_bound": "0.10"},
        (),
        command_id="batch-1",
    )
    committed = read_engineering_snapshot(updated)
    states = [step["state"] for step in updated.flow.steps()]
    names = [step["name"] for step in updated.flow.steps()]
    first = names.index("place")

    assert committed["workspaceRevision"] == 2
    assert committed["flow"] == json.loads(
        (Path(updated.directory) / "home" / "flow.json").read_text(encoding="utf-8")
    )
    assert states[:first] == ["Success"] * first
    assert all(state == "Unstart" for state in states[first:])
    assert updated.parameters.data["dreamplace"]["target_density"] == 0.65

    repeated = apply_workspace_parameters(
        workspace.directory,
        1,
        {"place.target_density": 0.65, "cts.skew_bound": "0.10"},
        (),
        command_id="batch-1",
    )
    assert read_engineering_snapshot(repeated)["workspaceRevision"] == 2

    restored = apply_workspace_parameters(
        workspace.directory,
        2,
        {},
        ("place.target_density", "cts.skew_bound"),
        command_id="batch-2",
    )
    assert read_engineering_snapshot(restored)["workspaceRevision"] == 3
    assert restored.parameters.data["dreamplace"]["target_density"] == baseline_density


def test_workspace_parameter_batch_rejects_step_mismatch_without_writes(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    before_params = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = read_engineering_snapshot(workspace)

    with pytest.raises(WorkspaceLifecycleError) as mismatch:
        apply_workspace_parameters(
            workspace.directory,
            1,
            {"cts.skew_bound": "0.10"},
            (),
            step_id="placement",
        )

    assert mismatch.value.code == "parameter_not_applicable"
    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_params
    assert read_engineering_snapshot(workspace) == before_snapshot


def test_published_step_parameter_update_preserves_current_step(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    placements = [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]

    updated = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": placements},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-1",
    )

    states = {step["name"]: step["state"] for step in updated.flow.steps()}
    committed = read_engineering_snapshot(updated)
    assert states["macroPlacement"] == "Success"
    assert states["postFloorplan"] == "Unstart"
    assert committed["flow"] == updated.flow.data
    assert committed["stalePredecessor"]["invalidatedStepIds"][0] == "postFloorplan"
    assert updated.parameters.data["macro"]["placements"] == placements
    from chipcompiler.data.workspace.macro_location import parse_macro_location_tcl

    macro_location_path = updated.config["macro_location"]
    assert parse_macro_location_tcl(macro_location_path.read_text()) == placements


def test_published_macro_parameter_update_rejects_mismatched_handoff_without_writes(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    before_params = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = (workspace.directory / "home" / "engineering-snapshot.json").read_bytes()
    before_flow = (workspace.directory / "home" / "flow.json").read_bytes()
    macro_location_path = workspace.config["macro_location"]
    before_macro_location = macro_location_path.read_bytes()
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)

    with pytest.raises(WorkspaceLifecycleError) as rejected:
        apply_workspace_parameters(
            workspace.directory,
            initial["workspaceRevision"],
            {
                "macro.placements": [
                    {"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}
                ]
            },
            (),
            step_id="macroPlacement",
            commit_step_output=True,
            command_id="published-macro-mismatch",
        )

    assert rejected.value.code == "step_output_mismatch"
    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_params
    assert (
        workspace.directory / "home" / "engineering-snapshot.json"
    ).read_bytes() == before_snapshot
    assert (workspace.directory / "home" / "flow.json").read_bytes() == before_flow
    assert macro_location_path.read_bytes() == before_macro_location


@pytest.mark.parametrize(
    ("handoff", "expected_code"),
    [
        (None, "step_output_not_published"),
        ("placeInstance u_ram0 10 nope R0\n", "step_output_invalid"),
        (
            "placeInstance u_ram0 10 20 R0\nplaceInstance u_stale 1 2 R90\n",
            "step_output_mismatch",
        ),
    ],
)
def test_published_macro_parameter_update_rejects_invalid_handoff_without_writes(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, handoff, expected_code
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    macro_location_path = workspace.config["macro_location"]
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    if handoff is None:
        macro_location_path.unlink()
    else:
        macro_location_path.write_text(handoff)
    before_params = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = (workspace.directory / "home" / "engineering-snapshot.json").read_bytes()
    before_flow = (workspace.directory / "home" / "flow.json").read_bytes()
    before_macro_location = (
        macro_location_path.read_bytes() if macro_location_path.exists() else None
    )

    with pytest.raises(WorkspaceLifecycleError) as rejected:
        apply_workspace_parameters(
            workspace.directory,
            initial["workspaceRevision"],
            {
                "macro.placements": [
                    {"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}
                ]
            },
            (),
            step_id="macroPlacement",
            commit_step_output=True,
            command_id=f"published-macro-invalid-{expected_code}",
        )

    assert rejected.value.code == expected_code
    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_params
    assert (
        workspace.directory / "home" / "engineering-snapshot.json"
    ).read_bytes() == before_snapshot
    assert (workspace.directory / "home" / "flow.json").read_bytes() == before_flow
    assert (
        macro_location_path.read_bytes() if macro_location_path.exists() else None
    ) == before_macro_location


def test_published_macro_parameter_update_accepts_rendered_float_precision(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    placements = [{"instance": "u_ram0", "x": 10.123456789, "y": 20.987654321, "orientation": "R0"}]

    updated = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": placements},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-precision",
    )

    from chipcompiler.data.workspace.macro_location import (
        parse_macro_location_tcl,
        render_macro_location_tcl,
    )

    assert updated.parameters.data["macro"]["placements"] == placements
    assert parse_macro_location_tcl(
        updated.config["macro_location"].read_text()
    ) == parse_macro_location_tcl(render_macro_location_tcl(placements))


def test_published_macro_parameter_update_publishes_mixed_orientations(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data.workspace.macro_location import (
        MACRO_ORIENTATIONS,
        parse_macro_location_tcl,
    )

    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    placements = [
        {
            "instance": f"u_macro_{index}",
            "x": 10.0 + index,
            "y": 20.0 + index,
            "orientation": orientation,
        }
        for index, orientation in enumerate(sorted(MACRO_ORIENTATIONS))
    ]

    updated = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": placements},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-orientations",
    )

    states = {step["name"]: step["state"] for step in updated.flow.steps()}
    assert updated.parameters.data["macro"]["placements"] == placements
    assert parse_macro_location_tcl(updated.config["macro_location"].read_text()) == placements
    assert states["macroPlacement"] == "Success"
    assert states["postFloorplan"] == "Unstart"


def test_published_macro_parameter_update_rejects_duplicate_instances(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    before_params = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = (workspace.directory / "home" / "engineering-snapshot.json").read_bytes()

    with pytest.raises(WorkspaceLifecycleError) as rejected:
        apply_workspace_parameters(
            workspace.directory,
            initial["workspaceRevision"],
            {
                "macro.placements": [
                    {"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"},
                    {"instance": "u_ram0", "x": 30.0, "y": 40.0, "orientation": "R90"},
                ]
            },
            (),
            step_id="macroPlacement",
            commit_step_output=True,
            command_id="published-macro-duplicate",
        )

    assert rejected.value.code == "invalid_parameter"
    assert "duplicates instance u_ram0" in str(rejected.value)
    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_params
    assert (
        workspace.directory / "home" / "engineering-snapshot.json"
    ).read_bytes() == before_snapshot


def test_published_macro_parameter_update_checks_unchanged_handoff(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    placements = [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]
    updated = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": placements},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-initial",
    )
    updated.config["macro_location"].write_text("# stale handoff\n")

    with pytest.raises(WorkspaceLifecycleError) as rejected:
        apply_workspace_parameters(
            workspace.directory,
            read_engineering_snapshot(updated)["workspaceRevision"],
            {"macro.placements": placements},
            (),
            step_id="macroPlacement",
            commit_step_output=True,
            command_id="published-macro-unchanged",
        )

    assert rejected.value.code == "step_output_mismatch"


def test_published_macro_parameter_update_can_clear_all_placements(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    placements = [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]
    published = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": placements},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-before-clear",
    )

    cleared = apply_workspace_parameters(
        workspace.directory,
        read_engineering_snapshot(published)["workspaceRevision"],
        {"macro.placements": []},
        (),
        step_id="macroPlacement",
        commit_step_output=True,
        command_id="published-macro-clear",
    )

    states = {step["name"]: step["state"] for step in cleared.flow.steps()}
    assert cleared.parameters.data["macro"]["placements"] == []
    assert cleared.config["macro_location"].read_text().strip() == (
        "# Auto-generated macro location file"
    )
    assert states["macroPlacement"] == "Success"
    assert states["postFloorplan"] == "Unstart"


def test_published_step_parameter_update_requires_success_without_writes(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:2]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    before_params = (workspace.directory / "home" / "params.toml").read_bytes()
    before_snapshot = (workspace.directory / "home" / "engineering-snapshot.json").read_bytes()

    with pytest.raises(WorkspaceLifecycleError) as rejected:
        apply_workspace_parameters(
            workspace.directory,
            initial["workspaceRevision"],
            {
                "macro.placements": [
                    {"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}
                ]
            },
            (),
            step_id="macroPlacement",
            commit_step_output=True,
            command_id="published-macro-2",
        )

    assert rejected.value.code == "step_output_not_published"
    assert (workspace.directory / "home" / "params.toml").read_bytes() == before_params
    assert (
        workspace.directory / "home" / "engineering-snapshot.json"
    ).read_bytes() == before_snapshot


def test_macro_placements_without_output_commit_invalidates_current_step(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )

    updated = apply_workspace_parameters(
        workspace.directory,
        initial["workspaceRevision"],
        {"macro.placements": [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]},
        (),
        step_id="macroPlacement",
        command_id="ordinary-macro-1",
    )

    states = {step["name"]: step["state"] for step in updated.flow.steps()}
    assert states["macroPlacement"] == "Unstart"
    assert states["postFloorplan"] == "Unstart"


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


def test_read_workspace_configuration_does_not_materialize_missing_runtime_files(
    tmp_path, minimal_ics55_pdk_factory
):
    import shutil

    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)
    checklist_file = workspace.directory / "home" / "checklist.json"
    log_dir = workspace.directory / "log"
    checklist_file.unlink(missing_ok=True)
    if log_dir.exists():
        shutil.rmtree(log_dir)
    shutil.rmtree(Path(bindings["pdk"]["root"]))

    configuration = read_workspace_configuration_from_directory(workspace.directory)
    readonly_workspace = load_workspace(workspace.directory, read_only=True)
    from chipcompiler.tools.ecc.signoff_checklist import rebuild_home_checklist

    rebuild_home_checklist(readonly_workspace, persist=False)

    assert configuration["workspaceSpec"]["pdk"]["familyId"] == "ics55"
    assert not checklist_file.exists()
    assert not log_dir.exists()


def test_step_configuration_update_invalidates_only_target_suffix(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    for step in flow.workspace.flow.data.get("steps", [])[:3]:
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
        "display_key",
        "knob_id",
    }
    states = {step["name"]: step["state"] for step in updated.flow.steps()}
    assert states["Synthesis"] == "Success"
    assert states["preFloorplan"] == "Unstart"
    assert states["macroPlacement"] == "Unstart"
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


def test_manual_macro_placement_is_editable_with_floorplan_configuration(
    tmp_path, minimal_ics55_pdk_factory
):
    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")

    configuration = read_step_configuration(workspace, "Floorplan")
    record = next(
        item for item in configuration["parameters"] if item["param"] == "macro.manual_placement"
    )
    assert record["value"] is False
    assert record["display_key"] == "manual_macro_placement"

    updated = update_workspace_step_configuration(
        workspace.directory,
        configuration["workspaceRevision"],
        "Floorplan",
        {"macro.manual_placement": True},
        "step-configuration-manual-macro",
    )

    assert updated.parameters.data["macro"]["manual_placement"] is True


def test_macro_placements_apply_prunes_stale_tcl_when_emptied(tmp_path, minimal_ics55_pdk_factory):
    """§20.5.4: the macro-import commit path keeps params.toml and
    macro_location.tcl consistent — an empty import after a non-empty one
    leaves no stale placeInstance lines."""
    from chipcompiler.data.workspace.macro_location import (
        MACRO_LOCATION_MARKER,
        macro_placements,
    )

    spec, bindings = _workspace_spec_fixture()
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    tcl = Path(workspace.directory) / "config" / "macro_location.tcl"
    placements = [{"instance": "u_ram0", "x": 10.0, "y": 20.0, "orientation": "R0"}]

    apply_workspace_parameters(
        workspace.directory,
        1,
        {"macro.placements": placements},
        (),
        command_id="macro-1",
    )
    assert "placeInstance u_ram0" in tcl.read_text()

    apply_workspace_parameters(
        workspace.directory,
        2,
        {"macro.placements": []},
        (),
        command_id="macro-2",
    )

    text = tcl.read_text()
    assert "placeInstance" not in text
    assert text == f"{MACRO_LOCATION_MARKER}\n\n"
    updated = load_workspace(workspace.directory)
    assert macro_placements(updated) == []
