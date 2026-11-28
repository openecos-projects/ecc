"""iMJ antenna verification runner and report/coverage helpers."""

import shutil
from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.utility import json_read
from chipcompiler.utility.json import finite_number

_DIAGNOSTIC_KEYS = (
    "skipped_segments",
    "conductors_out_of_range",
    "partial_areas_dropped",
)


def _nonnegative_int(value: object) -> int | None:
    number = finite_number(value)
    if number is None or number < 0:
        return None
    if isinstance(number, float) and not number.is_integer():
        return None
    return int(number)


def read_antenna_check(step_json: str | Path | None) -> dict | None:
    """Return the ``antenna_check`` block of the step JSON, or None when unreadable."""
    if not step_json:
        return None
    data = json_read(str(step_json))
    block = data.get("antenna_check") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else None


def antenna_diagnostics(block: dict | None) -> list[str]:
    """Return non-zero skipped/dropped geometry counters as strings."""
    if block is None:
        return []
    items = []
    for key in _DIAGNOSTIC_KEYS:
        val = _nonnegative_int(block.get(key))
        if val is not None and val > 0:
            items.append(f"{key}={val}")
    return items


def antenna_coverage(block: dict | None) -> tuple[bool, str]:
    """Return ``(verified, message)`` for an ``antenna_check`` block."""
    if block is None:
        return False, "Antenna check result is missing or unreadable; the design was not verified."
    nets = _nonnegative_int(block.get("signal_net_count"))
    pins = _nonnegative_int(block.get("pins_with_gate_area"))
    reasons = []
    if nets is None or nets <= 0:
        reasons.append("0 nets were analysed (no antenna rules in the loaded tech LEF?)")
    if pins is None or pins <= 0:
        reasons.append("0 gate pins have ANTENNAGATEAREA (missing in the cell LEFs?)")
    if reasons:
        return False, "Antenna check is not verified: " + "; ".join(reasons) + "."
    diags = antenna_diagnostics(block)
    base = f"Antenna check analysed {nets} nets and {pins} gate pins."
    if diags:
        return True, f"{base} Diagnostics: {', '.join(diags)}."
    return True, base


def antenna_check_metrics(step_json: str | Path | None) -> dict[str, int]:
    """Extract validated integer metrics from ``antenna_check.step.json``."""
    block = read_antenna_check(step_json)
    if block is None:
        return {}
    metrics: dict[str, int] = {}
    for metric_id, key in (
        ("antenna_violation_count", "violation_count"),
        ("antenna_signal_net_count", "signal_net_count"),
        ("antenna_gate_pin_count", "pins_with_gate_area"),
    ):
        count = _nonnegative_int(block.get(key))
        if count is not None:
            metrics[metric_id] = count
    return metrics


def run_antenna_check(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    from chipcompiler.tools.ecc import runner

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    data_dir = step.data.steps[StepEnum.ANTENNA_CHECK.value]
    native_report = data_dir / "antenna_checker" / "antenna_check.rpt"
    report_path = step.report.step
    step_json_path = step.feature.step
    if report_path is None:
        raise ValueError("Antenna check report path is not configured")
    if step_json_path is None:
        raise ValueError("Antenna check step JSON path is not configured")
    # A failed rerun must not expose an old report as the current result.
    native_report.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)
    step_json_path.unlink(missing_ok=True)

    ecc_module = runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)
    if ecc_module is None:
        sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Success)

    sub_flow.update_step(EccSubFlowEnum.check_antenna.value, StateEnum.Ongoing)
    completed = False
    try:
        if not ecc_module.init_mj(output_dir=data_dir):
            workspace.logger.error("Failed to initialize iMJ for antenna checking")
            return False
        try:
            checked = ecc_module.check_antenna(step_json=step_json_path)
        finally:
            destroyed = ecc_module.destroy_mj()
        if not checked or not destroyed:
            workspace.logger.error("iMJ antenna check failed")
            return False
        if not native_report.is_file():
            workspace.logger.error("Antenna check report is missing: %s", native_report)
            return False
        if not step_json_path.is_file():
            workspace.logger.error("Antenna check step JSON is missing: %s", step_json_path)
            return False
        report_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native_report, report_path)
        # Success means execution/reporting completed, not zero violations
        # or complete antenna-rule coverage in the technology/cell LEFs.
        # Coverage is judged by the signoff checklist (quality.antenna.coverage);
        # say so here too so a vacuous run is not mistaken for a clean one.
        verified, message = antenna_coverage(read_antenna_check(step_json_path))
        if not verified:
            workspace.logger.warning("%s", message)
        completed = True
    finally:
        sub_flow.update_step(
            EccSubFlowEnum.check_antenna.value,
            StateEnum.Success if completed else StateEnum.Imcomplete,
        )

    if not runner.save_data(
        workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
    ):
        sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Success)
    return True
