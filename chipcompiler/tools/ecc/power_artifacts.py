"""iPW power-report publication and workspace lookup helpers."""

import shutil
from pathlib import Path

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc.sta_qor import (
    STA_POWER_REPORT_FILENAME,
    STA_POWER_SUMMARY_FILENAME,
    read_sta_power_summary,
    sta_power_summary_payload,
)
from chipcompiler.utility import json_write


def power_report_path(data_dir: str | Path) -> Path:
    """Return iPW's native power report below its configured data directory."""
    return Path(data_dir) / "power_reporter" / STA_POWER_REPORT_FILENAME


def power_summary_path(feature_dir: str | Path) -> Path:
    """Return ECC's machine-readable summary location for a power step."""
    return Path(feature_dir) / STA_POWER_SUMMARY_FILENAME


def power_step_path(feature_dir: str | Path) -> Path:
    """Return the merged machine-readable power step artifact."""
    return Path(feature_dir) / "powerAnalysis.step.json"


def native_power_report_path(power_step_directory: str | Path) -> Path:
    """Return the native iPW report of a powerAnalysis step."""
    return power_report_path(Path(power_step_directory) / "data" / "pw")


def published_power_report_path(power_step_directory: str | Path) -> Path:
    """Return the report a powerAnalysis step publishes."""
    return Path(power_step_directory) / "report" / f"{StepEnum.POWER_ANALYSIS.value}.rpt"


def power_report_source_path(power_step_directory: str | Path) -> Path:
    """Return the current power report, falling back to legacy iPW workspaces."""
    published = published_power_report_path(power_step_directory)
    return published if published.is_file() else native_power_report_path(power_step_directory)


def step_power_summary_path(power_step_directory: str | Path) -> Path:
    """Return the ECC power summary of a powerAnalysis step."""
    return power_summary_path(Path(power_step_directory) / "feature")


def instance_power_path(power_step_directory: str | Path) -> Path:
    """Return iPW's per-instance power TSV consumed by iEMIR."""
    return native_power_report_path(power_step_directory).with_name("instance_power.tsv")


def discard_power_artifacts(
    data_dir: str | Path,
    feature_dir: str | Path,
    report_path: str | Path | None = None,
) -> None:
    """Invalidate raw and derived power artifacts before an iPW rerun."""
    power_report_path(data_dir).unlink(missing_ok=True)
    power_summary_path(feature_dir).unlink(missing_ok=True)
    power_step_path(feature_dir).unlink(missing_ok=True)
    if report_path:
        Path(report_path).unlink(missing_ok=True)


def publish_power_report(data_dir: str | Path, report_path: str | Path) -> Path:
    """Atomically copy iPW's native report to the step report path."""
    source_path = power_report_path(data_dir)
    if not source_path.is_file():
        raise FileNotFoundError(f"iPW power report does not exist: {source_path}")

    target_path = Path(report_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    shutil.copy2(source_path, temporary_path)
    temporary_path.replace(target_path)
    return target_path


def publish_power_summary(data_dir: str | Path, feature_dir: str | Path) -> Path:
    """Parse iPW's report and atomically publish ECC's JSON power summary."""
    report_path = power_report_path(data_dir)
    if not report_path.is_file():
        raise FileNotFoundError(f"iPW power report does not exist: {report_path}")

    summary = read_sta_power_summary(report_path)
    if summary is None:
        raise ValueError(f"iPW power report is not parseable: {report_path}")

    summary_path = power_summary_path(feature_dir)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    payload = sta_power_summary_payload(summary)
    if not json_write(summary_path, payload):
        raise OSError(f"Failed to write iPW power summary: {summary_path}")
    step_path = power_step_path(feature_dir)
    step_payload = {
        "schema_version": 1,
        "step": StepEnum.POWER_ANALYSIS.value,
        "power_summary": payload,
    }
    if not json_write(step_path, step_payload):
        raise OSError(f"Failed to write merged power step artifact: {step_path}")
    return summary_path
