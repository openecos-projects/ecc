"""Engine parameter edits: step scope, flow membership and invalidation start."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.engine import (
    EngineFlow,
    WorkspaceLifecycleError,
    apply_workspace_parameters,
    create_workspace_from_spec,
    update_workspace_from_spec,
    update_workspace_step_configuration,
)
from chipcompiler.engine.snapshot import create_engineering_snapshot, read_engineering_snapshot
from chipcompiler.params import lookup_schema, workspace_param_value
from test.flow_fixture import step_fields


def _spec() -> tuple[dict, dict]:
    root = Path(__file__).parents[1] / "fixtures" / "workspace_spec"
    payload = json.loads((root / "valid.json").read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {key: str(root / value) for key, value in bindings["inputs"].items()}
    return payload["workspaceSpec"], bindings


def _workspace(tmp_path, pdk_factory, *, diff_opt: bool = False):
    """A committed rtl2gds Workspace whose steps all ran successfully.

    *diff_opt* enables the (by default skipped) diff_opt step after placement.
    """
    spec, bindings = _spec()
    bindings["pdk"]["root"] = str(pdk_factory(tmp_path / "pdk"))
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings, "create-1")
    flow = EngineFlow(workspace)
    steps = flow.workspace.flow.data["steps"]
    if diff_opt:
        index = next(i for i, step in enumerate(steps) if step["name"] == "placement")
        steps.insert(
            index + 1,
            {**steps[index], "name": "diff_opt", **step_fields("diff_opt", "dreamplace")},
        )
    for step in steps:
        step["state"] = "Success"
    assert flow.save()
    initial = read_engineering_snapshot(workspace)
    create_engineering_snapshot(
        workspace,
        workspace_id=initial["workspaceId"],
        workspace_revision=initial["workspaceRevision"],
    )
    return workspace, bindings


def _states_from(workspace, first: str) -> dict[str, str]:
    """The state every flow step must have once *first* and its suffix are invalidated."""
    names = [step["name"] for step in workspace.flow.steps()]
    start = names.index(first)
    return {name: "Success" if index < start else "Unstart" for index, name in enumerate(names)}


def _states(workspace) -> dict[str, str]:
    return {step["name"]: step["state"] for step in workspace.flow.steps()}


def test_a_routing_layer_edited_at_routing_invalidates_the_dreamplace_steps_reading_it(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    workspace, _ = _workspace(tmp_path, minimal_ics55_pdk_factory)

    updated = update_workspace_step_configuration(
        workspace.directory, 1, "routing", {"route.top_layer": "MET6"}, "top-layer-1"
    )

    # The layer also feeds DreamPlace's gpugr layers, which macro_placement reads first.
    expected = _states_from(workspace, "macro_placement")
    assert _states(updated) == expected
    snapshot_steps = read_engineering_snapshot(updated)["flow"]["steps"]
    assert {step["name"]: step["state"] for step in snapshot_steps} == expected


def test_a_diff_opt_value_invalidates_from_diff_opt_and_keeps_placement(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    workspace, _ = _workspace(tmp_path, minimal_ics55_pdk_factory, diff_opt=True)
    schema = lookup_schema("place.timing_sizing_action")
    assert schema is not None
    baseline = workspace_param_value(workspace, schema, step="placement")
    other = next(choice for choice in schema.choices if choice != baseline)

    updated = apply_workspace_parameters(
        workspace.directory, 1, {"diff_opt:place.timing_sizing_action": other}, ()
    )

    assert _states(updated) == _states_from(workspace, "diff_opt")
    assert {
        step: workspace_param_value(updated, schema, step=step)
        for step in ("placement", "diff_opt")
    } == {"placement": baseline, "diff_opt": other}


@pytest.mark.parametrize(
    "edit",
    [
        lambda directory: apply_workspace_parameters(
            directory, 1, {"legalization:place.target_density": 0.6}, ()
        ),
        lambda directory: apply_workspace_parameters(
            directory, 1, {"place.target_density": 0.6}, (), step_id="legalization"
        ),
        lambda directory: update_workspace_step_configuration(
            directory, 1, "legalization", {"place.target_density": 0.6}
        ),
    ],
    ids=["qualified", "step_id", "step_configuration"],
)
def test_no_dreamplace_parameter_is_settable_at_legalization(
    tmp_path, minimal_ics55_pdk_factory, edit
) -> None:
    workspace, _ = _workspace(tmp_path, minimal_ics55_pdk_factory)
    before = (Path(workspace.directory) / "home" / "params.toml").read_bytes()

    with pytest.raises(WorkspaceLifecycleError) as error:
        edit(workspace.directory)

    assert error.value.code == "parameter_not_applicable"
    assert (Path(workspace.directory) / "home" / "params.toml").read_bytes() == before


def test_every_step_value_of_a_batch_must_name_a_step_of_the_flow(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    # The default rtl2gds flow skips diff_opt.
    workspace, _ = _workspace(tmp_path, minimal_ics55_pdk_factory)
    before = (Path(workspace.directory) / "home" / "params.toml").read_bytes()

    with pytest.raises(WorkspaceLifecycleError) as error:
        apply_workspace_parameters(
            workspace.directory,
            1,
            {"placement:place.target_density": 0.6, "diff_opt:place.timing_sizing_action": "up"},
            (),
        )

    assert error.value.code == "unknown_flow_step"
    assert (Path(workspace.directory) / "home" / "params.toml").read_bytes() == before


def test_a_rebuild_carries_step_values_into_a_flow_that_keeps_their_step(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    workspace, bindings = _workspace(tmp_path, minimal_ics55_pdk_factory)
    apply_workspace_parameters(workspace.directory, 1, {"placement:place.target_density": 0.6}, ())
    spec, _ = _spec()
    spec = deepcopy(spec)
    spec["design"]["clockPort"] = "clock"

    updated = update_workspace_from_spec(workspace.directory, 2, spec, bindings, "carry-1")

    assert updated.workspace.parameters.data["step_params"] == {
        "placement": {"place.target_density": 0.6}
    }


def test_a_rebuild_rejects_step_values_whose_step_leaves_the_flow(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    workspace, bindings = _workspace(tmp_path, minimal_ics55_pdk_factory)
    apply_workspace_parameters(workspace.directory, 1, {"placement:place.target_density": 0.6}, ())
    spec, _ = _spec()
    spec = deepcopy(spec)
    spec["flow"] = {"flowId": "syn_sta"}

    with pytest.raises(WorkspaceLifecycleError) as error:
        update_workspace_from_spec(workspace.directory, 2, spec, bindings, "carry-1")

    assert (error.value.code, error.value.details) == (
        "workspace_spec_invalid",
        {"issues": ["placement:place.target_density: step placement is not in the new flow"]},
    )


def test_the_configuration_projection_carries_each_step_value(
    tmp_path, minimal_ics55_pdk_factory
) -> None:
    workspace, _bindings = _workspace(tmp_path, minimal_ics55_pdk_factory)
    revision = read_engineering_snapshot(workspace)["workspaceRevision"]

    updated = apply_workspace_parameters(
        workspace.directory, revision, {"placement:place.target_density": 0.71}, ()
    )

    parameters = read_engineering_snapshot(updated)["workspaceSpec"]["parameters"]
    baseline = workspace_param_value(updated, lookup_schema("place.target_density"))
    assert {
        key: parameters.get(key)
        for key in ("place.target_density", "placement:place.target_density")
    } == {"place.target_density": baseline, "placement:place.target_density": 0.71}
