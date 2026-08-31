#!/usr/bin/env python
import json
import os
import subprocess
from pathlib import Path

from chipcompiler.data import StateEnum, Workspace, YosysLecStep
from chipcompiler.tools.yosys.utility import get_yosys_runtime
from chipcompiler.tools.yosys_lec.subflow import YosysLecSubFlow
from chipcompiler.utility import file_digest


def _status_is_proven(path: Path | str | None) -> bool:
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    return (
        "Equivalence successfully proven!" in text
        or "Found a total of 0 unproven $equiv cells." in text
    )


def _netlist_fields(path: Path | str | None) -> dict:
    digest = file_digest(path)
    return {
        "path": str(path or ""),
        "sha256": digest[0] if digest else "",
        "size_bytes": digest[1] if digest else 0,
    }


def _write_result(step: YosysLecStep, *, proven: bool) -> None:
    if not step.output.json:
        return
    golden = _netlist_fields(step.input.golden_verilog)
    gate = _netlist_fields(step.input.gate_verilog)
    payload = {
        "status": "proven" if proven else "incomplete",
        "golden_verilog": golden["path"],
        "gate_verilog": gate["path"],
        "golden_sha256": golden["sha256"],
        "gate_sha256": gate["sha256"],
        "golden_size_bytes": golden["size_bytes"],
        "gate_size_bytes": gate["size_bytes"],
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
        _write_result(step, proven=False)
        return False

    for label, path in (
        ("golden netlist", step.input.golden_verilog),
        ("gate netlist", step.input.gate_verilog),
    ):
        if not path or not os.path.exists(path):
            sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
            Path(log_path).write_text(f"Error: missing {label}: {path}\n", encoding="utf-8")
            _write_result(step, proven=False)
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
        _write_result(step, proven=False)
        sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
        return False

    proven = result.returncode == 0 and _status_is_proven(step.report.equiv_status)
    _write_result(step, proven=proven)
    if proven:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Success)
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
        return True

    sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
    return False
