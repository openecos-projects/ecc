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


def discard_power_artifacts(data_dir: str | Path, feature_dir: str | Path) -> None:
    """Invalidate raw and derived power artifacts before an iPW rerun."""
    power_report_path(data_dir).unlink(missing_ok=True)
    power_summary_path(feature_dir).unlink(missing_ok=True)


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
    if not json_write(summary_path, sta_power_summary_payload(summary)):
        raise OSError(f"Failed to write iPW power summary: {summary_path}")
    return summary_path
