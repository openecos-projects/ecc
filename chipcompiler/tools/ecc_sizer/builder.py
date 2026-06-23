from __future__ import annotations

import os
import shutil

from rosettakit import cmdfile

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc import builder as ecc_builder

from .utility import find_sizer_root


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: str,
    input_verilog: str,
    input_db: str | None = None,
    output_def: str | None = None,
    output_verilog: str | None = None,
    output_gds: str | None = None,
) -> WorkspaceStep:
    safe_step_name = "_".join(step_name.split()).lower()
    step_directory = f"{workspace.directory}/{safe_step_name}_sizer"
    if output_def is None:
        output_def = f"{step_directory}/output/{workspace.design.name}_{safe_step_name}.def.gz"
    if output_verilog is None:
        output_verilog = f"{step_directory}/output/{workspace.design.name}_{safe_step_name}.v.gz"

    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool="sizer",
        step_directory=step_directory,
    )
    step.output["db"] = ""
    step.script["sizer_env"] = f"{step.script['dir']}/{workspace.design.name}.env_file"
    step.script["sizer_cmd"] = f"{step.script['dir']}/{workspace.design.name}.cmd_file"
    return step


def build_step_space(step: WorkspaceStep) -> None:
    ecc_builder.build_step_space(step)


def build_sub_flow(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    from .subflow import SizerSubFlow

    subflow = SizerSubFlow(workspace=workspace, workspace_step=workspace_step)
    subflow.build_sub_flow()


def build_checklist(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    from .checklist import SizerChecklist

    checklist = SizerChecklist(workspace=workspace, workspace_step=workspace_step)
    checklist.build_checklist()


def _copy_or_seed_template(template: str, target: str, fallback: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(template):
        shutil.copy2(template, target)
        return

    with open(target, "w", encoding="utf-8") as file:
        file.write(fallback)


def _append_text(path: str, text: str) -> None:
    with open(path, "a", encoding="utf-8") as file:
        file.write(text)


def _sizer_env_template() -> str:
    sizer_root = find_sizer_root()
    if sizer_root is None:
        return ""

    submit_dir = sizer_root / "submit"
    return str(submit_dir / "env_base_file")


def _tech_text(workspace: Workspace) -> str:
    sizer_root = find_sizer_root()
    env = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)
    env.option("lef", workspace.pdk.tech, value_type=cmdfile.ValueType.PATH, omit_empty=True)
    env.options("lef", workspace.pdk.lefs, value_type=cmdfile.ValueType.PATH)
    env.options("lib", workspace.pdk.libs, value_type=cmdfile.ValueType.PATH)

    if sizer_root is not None:
        tcl_path = sizer_root / "src" / "sizer_os.tcl"
        env.option("tclFile", str(tcl_path), value_type=cmdfile.ValueType.PATH)
    return env.build()


def _append_route_layer_options(command: cmdfile.CommandFile, workspace: Workspace) -> None:
    bottom = workspace.parameters.data.get("Bottom layer", "")
    top = workspace.parameters.data.get("Top layer", "")

    if bottom:
        command.option("min_route_layer", bottom)
    if top:
        command.option("max_route_layer", top)


def _cmd_text(workspace: Workspace, step: WorkspaceStep) -> str:
    output_dir = step.data.get(step.name, step.data["dir"])
    command = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)

    command.flag("useOpenSTA")
    command.option("top", workspace.design.top_module or workspace.design.name)
    command.option(
        "def",
        step.input.get("def", ""),
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "v",
        step.input.get("verilog", ""),
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "sdc",
        workspace.pdk.sdc,
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "spef",
        workspace.pdk.spef,
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option("outputPath", ".")
    command.option(
        "def_out_path",
        os.path.relpath(step.output["def"], output_dir),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "verilog_out_path",
        os.path.relpath(step.output["verilog"], output_dir),
        value_type=cmdfile.ValueType.PATH,
    )
    _append_route_layer_options(command, workspace)
    return command.build()


def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    env_template = _sizer_env_template()
    env_path = step.script["sizer_env"]
    cmd_path = step.script["sizer_cmd"]

    _copy_or_seed_template(env_template, env_path, "-num_vt 1\n")
    os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
    with open(cmd_path, "w", encoding="utf-8"):
        pass

    _append_text(env_path, _tech_text(workspace))
    _append_text(cmd_path, _cmd_text(workspace, step))

    build_sub_flow(workspace=workspace, workspace_step=step)
    build_checklist(workspace=workspace, workspace_step=step)
