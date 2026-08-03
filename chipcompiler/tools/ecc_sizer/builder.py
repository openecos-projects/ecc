from __future__ import annotations

import os
import shutil
from pathlib import Path

from rosettakit import cmdfile

from chipcompiler.data import EccStep, Workspace
from chipcompiler.tools.ecc import builder as ecc_builder

from .utility import find_sizer_root


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> EccStep:
    safe_step_name = "_".join(step_name.split()).lower()
    step_directory = Path(workspace.directory) / f"{safe_step_name}_sizer"
    if output_def is None:
        output_def = step_directory / "output" / f"{workspace.design.name}_{safe_step_name}.def.gz"
    if output_verilog is None:
        output_verilog = (
            step_directory / "output" / f"{workspace.design.name}_{safe_step_name}.v.gz"
        )

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
    step.output.db = ""
    # Sizer produces no geometry snapshot; leave the destination undeclared so
    # it is not part of this step's success contract (see EngineFlow.check_step_result).
    step.output.geometry = None
    step.output.geometry_manifest = None
    script_dir = step.script.dir or step_directory / "script"
    step.script.sizer_env = script_dir / f"{workspace.design.name}.env_file"
    step.script.sizer_cmd = script_dir / f"{workspace.design.name}.cmd_file"
    return step


def build_step_space(step: EccStep) -> None:
    ecc_builder.build_step_space(step)


def build_sub_flow(workspace: Workspace, workspace_step: EccStep) -> None:
    from .subflow import SizerSubFlow

    subflow = SizerSubFlow(workspace=workspace, workspace_step=workspace_step)
    subflow.build_sub_flow()


def build_checklist(workspace: Workspace, workspace_step: EccStep) -> None:
    from .checklist import SizerChecklist

    checklist = SizerChecklist(workspace=workspace, workspace_step=workspace_step)
    checklist.build_checklist()


def _copy_or_seed_template(template: Path | None, target: Path, fallback: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if template and template.exists():
        shutil.copy2(template, target)
        return

    with target.open("w", encoding="utf-8") as file:
        file.write(fallback)


def _append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(text)


def _sizer_env_template() -> Path | None:
    sizer_root = find_sizer_root()
    if sizer_root is None:
        return None

    submit_dir = sizer_root / "submit"
    return submit_dir / "env_base_file"


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


def _cmd_text(workspace: Workspace, step: EccStep) -> str:
    output_dir = step.data.workdir_for(step.name) or ""
    command = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)

    command.flag("useOpenSTA")
    command.option("top", workspace.design.top_module or workspace.design.name)
    command.option(
        "def",
        step.input.def_ or "",
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "v",
        step.input.verilog or "",
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
        os.path.relpath(step.output.def_ or "", output_dir),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "verilog_out_path",
        os.path.relpath(step.output.verilog or "", output_dir),
        value_type=cmdfile.ValueType.PATH,
    )
    _append_route_layer_options(command, workspace)
    return command.build()


def build_step_config(workspace: Workspace, step: EccStep) -> None:
    env_template = _sizer_env_template()
    env_path = step.script.sizer_env
    cmd_path = step.script.sizer_cmd
    if env_path is None or cmd_path is None:
        raise ValueError("sizer step is missing script env/cmd paths")

    _copy_or_seed_template(env_template, env_path, "-num_vt 1\n")
    Path(cmd_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(cmd_path).open("w", encoding="utf-8"):
        pass

    _append_text(env_path, _tech_text(workspace))
    _append_text(cmd_path, _cmd_text(workspace, step))

    build_sub_flow(workspace=workspace, workspace_step=step)
    build_checklist(workspace=workspace, workspace_step=step)
