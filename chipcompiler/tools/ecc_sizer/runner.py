from __future__ import annotations

import os
import subprocess

from chipcompiler.data import EccStep, StateEnum, Workspace

from .subflow import SizerSubFlow, SizerSubFlowEnum
from .utility import get_sizer_command, is_eda_exist, is_sizer_runtime_exist


def _has_required_outputs(step: EccStep) -> bool:
    return os.path.exists(step.output.def_ or "") and os.path.exists(step.output.verilog or "")


def run_step(
    workspace: Workspace,
    step: EccStep,
    ecc_module=None,
) -> StateEnum:
    del ecc_module

    sub_flow = SizerSubFlow(workspace=workspace, workspace_step=step)
    run_sizer_step = SizerSubFlowEnum.run_sizer.value

    if not is_eda_exist() or not is_sizer_runtime_exist():
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Invalid)
        return StateEnum.Invalid

    env_path = step.script.sizer_env or ""
    cmd_path = step.script.sizer_cmd or ""
    if not os.path.exists(env_path) or not os.path.exists(cmd_path):
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Invalid)
        return StateEnum.Invalid

    output_dir = step.data.workdir_for(step.name) or ""
    os.makedirs(output_dir, exist_ok=True)
    log_path = step.log.file or ""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    os.makedirs(os.path.dirname(step.output.def_ or ""), exist_ok=True)

    command = get_sizer_command() + ["-env", str(env_path), "-f", str(cmd_path)]
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            command,
            cwd=str(output_dir),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=False,
        )

    if result.returncode == 0 and _has_required_outputs(step):
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Success)
        return StateEnum.Success
    sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Imcomplete)
    return StateEnum.Imcomplete
