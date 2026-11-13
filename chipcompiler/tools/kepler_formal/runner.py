#!/usr/bin/env python
import os
import subprocess
from pathlib import Path

from chipcompiler.data import KeplerFormalStep, StateEnum, Workspace
from chipcompiler.tools.kepler_formal.subflow import KeplerFormalSubFlow
from chipcompiler.tools.kepler_formal.utility import get_kepler_formal_runtime
from chipcompiler.tools.lec_result import write_step_result
from chipcompiler.utility.path import MissingPathError, require_path

# kepler-formal LEC exits 0 whether the designs are equivalent or not; the
# verdict only appears in its stdout. Positive evidence is required for a
# proven result, mirroring how the upstream MCP wrapper classifies runs. SEC
# (lec@Synthesis) under its default dual-rail encoding words a proof as
# "No binary-defined difference was found."
_PROVEN_MARKERS = ("No difference was found.", "No binary-defined difference was found.")
_DIFFERENCE_MARKER = "Difference was found."


def _write_result(workspace: Workspace, step: KeplerFormalStep, *, proven: bool) -> None:
    from chipcompiler.tools.kepler_formal.builder import golden_kind

    write_step_result(step, proven=proven, golden_kind=golden_kind(workspace, step))


def _unidentified_rtl(workspace: Workspace, step: KeplerFormalStep) -> str:
    """Why the files an RTL golden reads cannot be identified; "" when they can."""
    from chipcompiler.tools.kepler_formal.builder import golden_kind
    from chipcompiler.utility.rtl_inputs import rtl_input_files

    kind = golden_kind(workspace, step)
    if kind == "netlist":
        return ""
    try:
        rtl_input_files(str(step.input.golden_verilog), filelist=kind == "rtl_filelist")
    except (OSError, ValueError) as exc:
        return f"cannot identify the files the RTL reads: {exc}"
    return ""


def _read_text(path: Path | str | None) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def _miter_verdict_lines(miter_log: Path | str | None) -> list[str]:
    text = _read_text(miter_log)
    return [line.strip() for line in text.splitlines() if "Circuits are" in line]


def _write_equiv_status(step: KeplerFormalStep) -> bool:
    try:
        target = require_path(step.report.equiv_status, "equivalence status")
    except MissingPathError:
        return False
    verdict_lines = _miter_verdict_lines(step.report.miter_log)
    target.write_text("\n".join(verdict_lines) + "\n", encoding="utf-8")
    return True


def _write_status_report(step: KeplerFormalStep, *, proven: bool, reason: str) -> bool:
    from chipcompiler.tools.kepler_formal.builder import checks_rtl

    check = "SEC of the RTL and the netlist" if checks_rtl(step) else "LEC"
    if proven:
        message = f"kepler-formal {check} completed with proven equivalence."
    else:
        message = f"kepler-formal {check} did not prove equivalence: {reason}"
    try:
        target = require_path(step.report.status, "status report")
    except MissingPathError:
        return False
    target.write_text(message + "\n", encoding="utf-8")
    return True


def _classify(log_text: str) -> tuple[bool, str]:
    """Classify a finished kepler-formal run from its captured stdout.

    A difference outranks any proof marker, so conflicting verdicts fail.
    """
    if _DIFFERENCE_MARKER in log_text:
        return False, "kepler-formal found a difference; see the miter log for details"
    if any(marker in log_text for marker in _PROVEN_MARKERS):
        return True, ""
    return False, "kepler-formal produced no equivalence verdict; inspect the step log"


def _prepare_compare_netlists(workspace: Workspace, step: KeplerFormalStep) -> tuple[Path, Path]:
    """Materialize kepler-formal-readable copies of the golden/gate netlists.

    An RTL golden (lec@Synthesis) is read as is. Digests in the result
    contract keep using the original inputs; the YAML is regenerated against
    these prepared paths right before execution.
    """
    from chipcompiler.tools.kepler_formal.builder import checks_rtl, write_step_config
    from chipcompiler.tools.kepler_formal.netlist_prep import physical_cell_names, prepare_netlist

    physical_cells = physical_cell_names(getattr(workspace, "pdk", None))
    data_dir = (
        Path(step.data.dir) if step.data.dir else require_path(step.directory, "step directory")
    )

    golden_source = require_path(step.input.golden_verilog, "golden netlist")
    golden = (
        golden_source
        if checks_rtl(step)
        else prepare_netlist(golden_source, data_dir / "golden_compare.v", physical_cells)
    )
    gate = prepare_netlist(
        require_path(step.input.gate_verilog, "gate netlist"),
        data_dir / "gate_compare.v",
        physical_cells,
    )
    write_step_config(workspace, step, golden_verilog=golden, gate_verilog=gate)
    return golden, gate


def run_step(workspace: Workspace, step: KeplerFormalStep, ecc_module=None) -> bool:
    sub_flow = KeplerFormalSubFlow(workspace=workspace, workspace_step=step)
    log_path = step.log.file or ""

    kepler_cmd, kepler_env = get_kepler_formal_runtime()
    if not kepler_cmd:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text("Error: kepler-formal is not available.\n", encoding="utf-8")
        _write_result(workspace, step, proven=False)
        _write_status_report(step, proven=False, reason="kepler-formal is not available")
        return False

    for label, path in (
        ("golden netlist", step.input.golden_verilog),
        ("gate netlist", step.input.gate_verilog),
    ):
        if not path or not os.path.exists(path):
            sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
            Path(log_path).write_text(f"Error: missing {label}: {path}\n", encoding="utf-8")
            _write_result(workspace, step, proven=False)
            _write_status_report(step, proven=False, reason=f"missing {label}: {path}")
            return False

    if reason := _unidentified_rtl(workspace, step):
        # A proof of RTL whose files cannot be identified could never be
        # checked for freshness (lec_result.input_digest): fail up front.
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text(f"Error: {reason}\n", encoding="utf-8")
        _write_result(workspace, step, proven=False)
        _write_status_report(step, proven=False, reason=reason)
        return False

    try:
        _prepare_compare_netlists(workspace, step)
    except (OSError, MissingPathError) as exc:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Invalid)
        Path(log_path).write_text(f"Error: preparing compare netlists: {exc}\n", encoding="utf-8")
        _write_result(workspace, step, proven=False)
        _write_status_report(step, proven=False, reason=f"preparing netlists failed: {exc}")
        return False

    try:
        cmd = kepler_cmd + [
            "--config",
            str(require_path(step.data.config, "kepler-formal config")),
        ]
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                cmd,
                cwd=str(require_path(step.directory, "step directory")),
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
        _write_result(workspace, step, proven=False)
        _write_equiv_status(step)
        _write_status_report(step, proven=False, reason=f"execution error: {exc}")
        sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
        return False

    log_text = _read_text(log_path)
    proven, reason = _classify(log_text)
    if result.returncode != 0:
        proven = False
        # SEC exits 3 on a counterexample: keep that verdict over the code.
        if _DIFFERENCE_MARKER not in log_text:
            reason = f"kepler-formal exited with code {result.returncode}"
    if not _write_equiv_status(step) or not _write_status_report(
        step, proven=proven, reason=reason
    ):
        sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
        return False
    _write_result(workspace, step, proven=proven)
    if proven:
        sub_flow.update_step(step_name="run lec", state=StateEnum.Success)
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
        return True

    sub_flow.update_step(step_name="run lec", state=StateEnum.Imcomplete)
    return False
