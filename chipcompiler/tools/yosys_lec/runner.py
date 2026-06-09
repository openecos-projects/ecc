#!/usr/bin/env python
import json
import os
import subprocess
from pathlib import Path

from chipcompiler.data import StateEnum, Workspace, YosysLecStep
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


def _write_result(step: YosysLecStep, proven: bool) -> None:
    payload = {
        "status": "proven" if proven else "incomplete",
        "equiv_status": str(step.report.equiv_status or ""),
        "status_report": str(step.report.status or ""),
    }
    Path(step.output.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_step(workspace: Workspace, step: YosysLecStep, ecc_module=None) -> bool:
    sub_flow = YosysLecSubFlow(workspace=workspace, workspace_step=step)
    log_path = step.log.file or ""

    yosys_cmd, yosys_env = get_yosys_runtime()
    if not yosys_cmd:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text("Error: yosys is not available.\n", encoding="utf-8")
        return False

    for label, path in (
        ("golden netlist", step.input.golden_verilog),
        ("gate netlist", step.input.gate_verilog),
    ):
        if not path or not os.path.exists(path):
            sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
            Path(log_path).write_text(f"Error: missing {label}: {path}\n", encoding="utf-8")
            return False

    cmd = yosys_cmd + ["-Q", "-c", Path(step.script.main).name]
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            cmd,
            cwd=str(step.script.dir or step.directory),
            env=yosys_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    proven = result.returncode == 0 and _status_is_proven(step.report.equiv_status)
    if proven:
        _write_result(step, proven=True)
        sub_flow.update_step(step_name="run lec", state=StateEnum.Success)
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
        return True

    sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
    return False
