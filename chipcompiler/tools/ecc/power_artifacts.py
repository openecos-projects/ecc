"""iPW power-report publication and workspace lookup helpers."""

from pathlib import Path

from chipcompiler.data import StepEnum
from chipcompiler.data.step import STEP_DIRECTORIES
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


def workspace_power_report_path(workspace_dir: str | Path) -> Path:
    """Return the canonical native iPW report path for a workspace."""
    return power_report_path(
        Path(workspace_dir) / STEP_DIRECTORIES[StepEnum.POWER_ANALYSIS.value] / "data" / "pw"
    )


def workspace_power_summary_path(workspace_dir: str | Path) -> Path:
    """Return the canonical ECC power-summary path for a workspace."""
    return power_summary_path(
        Path(workspace_dir) / STEP_DIRECTORIES[StepEnum.POWER_ANALYSIS.value] / "feature"
    )


def workspace_instance_power_path(workspace_dir: str | Path) -> Path:
    """Return iPW's per-instance power TSV consumed by iEMIR."""
    return workspace_power_report_path(workspace_dir).with_name("instance_power.tsv")


def discard_power_artifacts(data_dir: str | Path, feature_dir: str | Path) -> None:
    """Invalidate raw and derived power artifacts before an iPW rerun."""
    power_report_path(data_dir).unlink(missing_ok=True)
    power_summary_path(feature_dir).unlink(missing_ok=True)
    power_step_path(feature_dir).unlink(missing_ok=True)


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
        "metrics": {
            key: value
            for key, value in payload.items()
            if key != "schema_version" and isinstance(value, (int, float))
        },
    }
    if not json_write(step_path, step_payload):
        raise OSError(f"Failed to write merged power step artifact: {step_path}")
    return summary_path
