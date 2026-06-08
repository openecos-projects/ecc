from __future__ import annotations

import os
import subprocess

from chipcompiler.data import StateEnum, Workspace, WorkspaceStep

from .utility import get_sizer_command, is_eda_exist


def _has_required_outputs(step: WorkspaceStep) -> bool:
    return os.path.exists(step.output.get("def", "")) and os.path.exists(
        step.output.get("verilog", "")
    )


def run_step(
    workspace: Workspace,
    step: WorkspaceStep,
    ecc_module=None,
) -> StateEnum:
    del workspace, ecc_module

    if not is_eda_exist():
        return StateEnum.Invalid

    env_path = step.script.get("sizer_env", "")
    cmd_path = step.script.get("sizer_cmd", "")
    if not os.path.exists(env_path) or not os.path.exists(cmd_path):
        return StateEnum.Invalid

    output_dir = step.data.get(step.name, step.data["dir"])
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(step.log["file"]), exist_ok=True)
    os.makedirs(os.path.dirname(step.output["def"]), exist_ok=True)

    command = get_sizer_command() + ["-env", env_path, "-f", cmd_path]
    with open(step.log["file"], "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            command,
            cwd=output_dir,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=False,
        )

    if result.returncode == 0 and _has_required_outputs(step):
        return StateEnum.Success
    return StateEnum.Imcomplete
