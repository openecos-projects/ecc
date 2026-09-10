#!/usr/bin/env python
import json
import os
import subprocess
from pathlib import Path

from chipcompiler.data import StateEnum, Workspace, KeplerFormalStep
from chipcompiler.tools.kepler_formal.subflow import KeplerFormalSubFlow
from chipcompiler.tools.kepler_formal.utility import get_kepler_formal_runtime
from chipcompiler.utility import file_digest

# kepler-formal LEC exits 0 whether the designs are equivalent or not; the
# verdict only appears in its stdout. Positive evidence is required for a
# proven result, mirroring how the upstream MCP wrapper classifies runs.
_PROVEN_MARKER = "No difference was found."
_DIFFERENCE_MARKER = "Difference was found."


def _read_text(path: Path | str | None) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def _miter_verdict_lines(miter_log: Path | str | None) -> list[str]:
    text = _read_text(miter_log)
    return [line.strip() for line in text.splitlines() if "Circuits are" in line]


def _write_equiv_status(step: KeplerFormalStep) -> None:
    verdict_lines = _miter_verdict_lines(step.report.miter_log)
    Path(step.report.equiv_status).write_text("\n".join(verdict_lines) + "\n", encoding="utf-8")


def _write_status_report(step: KeplerFormalStep, *, proven: bool, reason: str) -> None:
    if proven:
        message = "kepler-formal LEC completed with proven equivalence."
    else:
        message = f"kepler-formal LEC did not prove equivalence: {reason}"
    Path(step.report.status).write_text(message + "\n", encoding="utf-8")


def _netlist_fields(path: Path | str | None) -> dict:
    digest = file_digest(path)
    return {
        "path": str(path or ""),
        "sha256": digest[0] if digest else "",
        "size_bytes": digest[1] if digest else 0,
    }


def _write_result(step: KeplerFormalStep, *, proven: bool) -> None:
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


def _classify(log_text: str) -> tuple[bool, str]:
    """Classify a finished kepler-formal run from its captured stdout."""
    if _PROVEN_MARKER in log_text:
        return True, ""
    if _DIFFERENCE_MARKER in log_text:
        return False, "kepler-formal found a difference; see the miter log for details"
    return False, "kepler-formal produced no equivalence verdict; inspect the step log"


def _prepare_compare_netlists(workspace: Workspace, step: KeplerFormalStep) -> tuple[Path, Path]:
    """Materialize kepler-formal-readable copies of the golden/gate netlists.

    Digests in the result contract keep using the original inputs; the YAML
    is regenerated against these prepared paths right before execution.
    """
    from chipcompiler.tools.kepler_formal.builder import write_step_config
    from chipcompiler.tools.kepler_formal.netlist_prep import physical_cell_names, prepare_netlist

    physical_cells = physical_cell_names(getattr(workspace, "pdk", None))
    data_dir = Path(step.data.dir or step.directory)

    golden = prepare_netlist(
        step.input.golden_verilog, data_dir / "golden_compare.v", physical_cells
    )
    gate = prepare_netlist(step.input.gate_verilog, data_dir / "gate_compare.v", physical_cells)
    write_step_config(workspace, step, golden_verilog=golden, gate_verilog=gate)
    return golden, gate


def run_step(workspace: Workspace, step: KeplerFormalStep, ecc_module=None) -> bool:
    sub_flow = KeplerFormalSubFlow(workspace=workspace, workspace_step=step)
    log_path = step.log.file or ""

    kepler_cmd, kepler_env = get_kepler_formal_runtime()
    if not kepler_cmd:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text("Error: kepler-formal is not available.\n", encoding="utf-8")
        _write_result(step, proven=False)
        _write_status_report(step, proven=False, reason="kepler-formal is not available")
        return False

    for label, path in (
        ("golden netlist", step.input.golden_verilog),
        ("gate netlist", step.input.gate_verilog),
    ):
        if not path or not os.path.exists(path):
            sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
            Path(log_path).write_text(f"Error: missing {label}: {path}\n", encoding="utf-8")
            _write_result(step, proven=False)
            _write_status_report(step, proven=False, reason=f"missing {label}: {path}")
            return False

    try:
        _prepare_compare_netlists(workspace, step)
    except OSError as exc:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text(f"Error: preparing compare netlists: {exc}\n", encoding="utf-8")
        _write_result(step, proven=False)
        _write_status_report(step, proven=False, reason=f"preparing netlists failed: {exc}")
        return False

    cmd = kepler_cmd + ["--config", str(step.data.config)]
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                cmd,
                cwd=str(step.directory),
                env=kepler_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        try:
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"Error running kepler-formal LEC: {exc}\n")
        except OSError:
            pass
        _write_result(step, proven=False)
        _write_equiv_status(step)
        _write_status_report(step, proven=False, reason=f"execution error: {exc}")
        sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
        return False

    _write_equiv_status(step)
    proven, reason = _classify(_read_text(log_path))
    if result.returncode != 0:
        proven = False
        reason = f"kepler-formal exited with code {result.returncode}"
    _write_result(step, proven=proven)
    _write_status_report(step, proven=proven, reason=reason)
    if proven:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Success)
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
        return True

    sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
    return False
