#!/usr/bin/env python
import os
import subprocess
from pathlib import Path

from chipcompiler.data import StateEnum, Workspace, YosysLecStep
from chipcompiler.tools.lec_result import write_step_result
from chipcompiler.tools.yosys.utility import get_yosys_runtime
from chipcompiler.tools.yosys_lec.subflow import YosysLecSubFlow


def _status_is_proven(path: Path | str | None) -> bool:
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    return (
        "Equivalence successfully proven!" in text
        or "Found a total of 0 unproven $equiv cells." in text
    )


def run_step(workspace: Workspace, step: YosysLecStep, ecc_module=None) -> bool:
    sub_flow = YosysLecSubFlow(workspace=workspace, workspace_step=step)
    log_path = step.log.file or ""

    yosys_cmd, yosys_env = get_yosys_runtime()
    if not yosys_cmd:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text("Error: yosys is not available.\n", encoding="utf-8")
        write_step_result(step, proven=False)
        return False

    for label, path in (
        ("golden netlist", step.input.golden_verilog),
        ("gate netlist", step.input.gate_verilog),
    ):
        if not path or not os.path.exists(path):
            sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
            Path(log_path).write_text(f"Error: missing {label}: {path}\n", encoding="utf-8")
            write_step_result(step, proven=False)
            return False

    cmd = yosys_cmd + ["-Q", "-c", Path(step.script.main).name]
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                cmd,
                cwd=str(step.script.dir or step.directory),
                env=yosys_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        try:
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"Error running yosys LEC: {exc}\n")
        except OSError:
            pass
        write_step_result(step, proven=False)
        sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
        return False

    proven = result.returncode == 0 and _status_is_proven(step.report.equiv_status)
    write_step_result(step, proven=proven)
    if proven:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Success)
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
        return True

    sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
    return False
