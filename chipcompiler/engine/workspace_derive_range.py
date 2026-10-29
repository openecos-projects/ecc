"""Freeze inherited entry inputs and bound a staged derived workspace's flow."""

import shutil
from pathlib import Path

from chipcompiler.data import Workspace, save_parameter
from chipcompiler.data.workspace.inputs import persist_origin_inputs
from chipcompiler.data.workspace_config import flow_section_from_flow_config
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
from chipcompiler.engine.workspace_reset import prepare_steps_for_rerun
from chipcompiler.rtl2gds import normalize_flow_step


def bound_derived_flow(
    workspace: Workspace, flow: EngineFlow, from_step: str, through_step: str
) -> None:
    records = workspace.flow.steps()
    names = [record["name"] for record in records]
    start = _step_index(names, from_step) if from_step else 0
    end = _step_index(names, through_step)
    if start > end:
        raise WorkspaceLifecycleError(
            "invalid_flow_range", f"Flow range is reversed: {from_step} -> {through_step}"
        )
    if start:
        entry = flow.workspace_steps[start]
        _freeze_entry_inputs(workspace, entry.input.verilog, entry.input.def_, entry.name)

    # Clear every downstream artifact before dropping ledger entries, so stale
    # outputs beyond the new endpoint cannot be mistaken for results of this flow.
    prepare_steps_for_rerun(workspace, flow, flow.workspace_steps[start:])
    workspace.flow.data["steps"] = records[start : end + 1]
    first = workspace.flow.data["steps"][0]
    first.pop("input_step", None)
    info = first.get("info", {})
    info.pop("input_step", None)
    if workspace.design.golden_verilog is not None and "golden_verilog" in info:
        info["golden_verilog"] = str(workspace.design.golden_verilog)
    config = {
        "start_step": names[start],
        "end_step": names[end],
        **{
            key: value
            for key, value in workspace.parameters.data.get("_flow", {}).items()
            if key in {"skip_steps", "lec_engine"}
        },
    }
    workspace.parameters.data["_flow"] = flow_section_from_flow_config(config)
    if not save_parameter(workspace.parameters) or not flow.save():
        raise OSError("Failed to persist derived flow range")
    flow.create_step_workspaces(executable_steps=set())


def _step_index(names: list[str], name: str) -> int:
    identity = normalize_flow_step(name).casefold()
    for index, candidate in enumerate(names):
        if normalize_flow_step(candidate).casefold() == identity:
            return index
    raise WorkspaceLifecycleError("flow_step_not_found", f"Flow Step not found: {name}")


def _freeze_entry_inputs(
    workspace: Workspace, netlist: Path | None, def_path: Path | None, step: str
) -> None:
    for role, path in (("netlist", netlist), ("DEF", def_path)):
        required = role == "netlist" or step != "preFloorplan"
        if required and (path is None or not path.is_file()):
            raise WorkspaceLifecycleError(
                "step_input_missing", f"{step} requires an existing source output {role}: {path}"
            )
    origin = workspace.directory / "origin"
    backup = workspace.directory / ".derive-origin"
    origin.rename(backup)
    origin.mkdir()
    workspace.pdk.sdc = _relocated_input(workspace.pdk.sdc, origin, backup)
    workspace.pdk.spef = _relocated_input(workspace.pdk.spef, origin, backup)
    golden = _relocated_input(workspace.design.golden_verilog, origin, backup)
    workspace.design.input_filelist = None
    workspace.parameters.data.pop("file_list", None)
    workspace.parameters.data["_input_mode"] = "postSynthesis"
    entry_def = _relocated_input(def_path, origin, backup)
    persist_origin_inputs(
        workspace,
        origin,
        workspace.directory,
        origin_def=entry_def if entry_def and entry_def.is_file() else None,
        origin_verilog=_relocated_input(netlist, origin, backup),
        input_filelist=None,
        golden_verilog=golden,
    )
    shutil.rmtree(backup)


def _relocated_input(path: Path | None, origin: Path, backup: Path) -> Path | None:
    if path is None or not path.is_relative_to(origin):
        return path
    return backup / path.relative_to(origin)
