from __future__ import annotations

import os
import shutil

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
        output_verilog = f"{step_directory}/output/{workspace.design.name}_{safe_step_name}.v"

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


def _append_lines(path: str, lines: list[str]) -> None:
    with open(path, "a", encoding="utf-8") as file:
        for line in lines:
            if line:
                file.write(f"{line}\n")


def _sizer_env_template() -> str:
    sizer_root = find_sizer_root()
    if sizer_root is None:
        return ""

    submit_dir = sizer_root / "submit"
    return str(submit_dir / "env_base_file")


def _tech_lines(workspace: Workspace) -> list[str]:
    sizer_root = find_sizer_root()
    lines = []
    if workspace.pdk.tech:
        lines.append(f"-lef {workspace.pdk.tech}")
    lines.extend(f"-lef {lef}" for lef in workspace.pdk.lefs)
    lines.extend(f"-lib {lib}" for lib in workspace.pdk.libs)

    if sizer_root is not None:
        tcl_path = sizer_root / "src" / "sizer_os.tcl"
        lines.append(f"-tclFile {tcl_path}")
    return lines


def _route_layer_lines(workspace: Workspace) -> list[str]:
    bottom = workspace.parameters.data.get("Bottom layer", "")
    top = workspace.parameters.data.get("Top layer", "")

    lines = []
    if bottom:
        lines.append(f"-min_route_layer {bottom}")
    if top:
        lines.append(f"-max_route_layer {top}")
    return lines


def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    env_template = _sizer_env_template()
    env_path = step.script["sizer_env"]
    cmd_path = step.script["sizer_cmd"]

    _copy_or_seed_template(env_template, env_path, "-num_vt 1\n")
    os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
    with open(cmd_path, "w", encoding="utf-8"):
        pass

    output_dir = step.data.get(step.name, step.data["dir"])
    cmd_lines = [
        "",
        "-useOpenSTA",
        f"-top {workspace.design.top_module or workspace.design.name}",
        f"-def {step.input.get('def', '')}",
    ]
    input_verilog = step.input.get("verilog", "")
    if input_verilog:
        cmd_lines.append(f"-v {input_verilog}")
    if workspace.pdk.sdc:
        cmd_lines.append(f"-sdc {workspace.pdk.sdc}")
    if workspace.pdk.spef:
        cmd_lines.append(f"-spef {workspace.pdk.spef}")
    cmd_lines.extend(
        [
            "-outputPath .",
            f"-def_out_path {os.path.relpath(step.output['def'], output_dir)}",
            f"-verilog_out_path {os.path.relpath(step.output['verilog'], output_dir)}",
        ]
    )
    cmd_lines.extend(_route_layer_lines(workspace))

    _append_lines(env_path, _tech_lines(workspace))
    _append_lines(cmd_path, cmd_lines)

    build_sub_flow(workspace=workspace, workspace_step=step)
    build_checklist(workspace=workspace, workspace_step=step)
