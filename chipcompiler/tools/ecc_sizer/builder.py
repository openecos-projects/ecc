from __future__ import annotations

import os
import shutil
from collections.abc import Iterable

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
    env = cmdfile.CommandFile(prefix="-")
    _sizer_option(env, "lef", workspace.pdk.tech, omit_empty=True)
    _sizer_options(env, "lef", workspace.pdk.lefs)
    _sizer_options(env, "lib", workspace.pdk.libs)

    if sizer_root is not None:
        tcl_path = sizer_root / "src" / "sizer_os.tcl"
        _sizer_option(env, "tclFile", str(tcl_path))
    return env.build(allow_unsafe_raw=True)


def _sizer_value(option: str, value: object) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"Sizer option -{option} cannot contain line breaks")
    if any(char.isspace() for char in text):
        raise ValueError(f"Sizer option -{option} cannot contain whitespace")
    return text


def _sizer_option(
    document: cmdfile.CommandFile,
    name: str,
    value: object,
    *,
    omit_empty: bool = False,
) -> None:
    if omit_empty and value == "":
        return
    # Sizer tokenizes config values on spaces and does not understand shell or Tcl quoting.
    document.raw_line(f"-{name} {_sizer_value(name, value)}")


def _sizer_options(
    document: cmdfile.CommandFile,
    name: str,
    values: Iterable[object],
    *,
    omit_empty: bool = False,
) -> None:
    for value in values:
        _sizer_option(document, name, value, omit_empty=omit_empty)


def _append_route_layer_options(command: cmdfile.CommandFile, workspace: Workspace) -> None:
    bottom = workspace.parameters.data.get("Bottom layer", "")
    top = workspace.parameters.data.get("Top layer", "")

    if bottom:
        _sizer_option(command, "min_route_layer", bottom)
    if top:
        _sizer_option(command, "max_route_layer", top)


def _cmd_text(workspace: Workspace, step: WorkspaceStep) -> str:
    output_dir = step.data.get(step.name, step.data["dir"])
    command = cmdfile.CommandFile(prefix="-")

    command.flag("useOpenSTA")
    _sizer_option(command, "top", workspace.design.top_module or workspace.design.name)
    _sizer_option(command, "def", step.input.get("def", ""), omit_empty=True)
    _sizer_option(command, "v", step.input.get("verilog", ""), omit_empty=True)
    _sizer_option(command, "sdc", workspace.pdk.sdc, omit_empty=True)
    _sizer_option(command, "spef", workspace.pdk.spef, omit_empty=True)
    _sizer_option(command, "outputPath", ".")
    _sizer_option(command, "def_out_path", os.path.relpath(step.output["def"], output_dir))
    _sizer_option(
        command,
        "verilog_out_path",
        os.path.relpath(step.output["verilog"], output_dir),
    )
    _append_route_layer_options(command, workspace)
    return command.build(allow_unsafe_raw=True)


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
