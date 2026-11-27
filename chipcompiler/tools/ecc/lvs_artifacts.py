"""Stale cleanup and report publication for LVS artifacts."""

import shutil
from pathlib import Path

from chipcompiler.data import EccStep, StepEnum, Workspace
from chipcompiler.utility import JsonReadError, json_read_strict
from chipcompiler.utility.path import optional_path


def _unlink_file(path: Path | None) -> None:
    if path is not None and path.is_file():
        path.unlink()


def _lvs_reporter_dir(step: EccStep) -> Path | None:
    output_dir = optional_path((step.data.steps or {}).get(StepEnum.LVS.value))
    if output_dir is None:
        return None
    return output_dir / "lvs_reporter"


def _has_valid_violations_payload(path: Path) -> bool:
    try:
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return False
    return isinstance(data, dict) and isinstance(data.get("violations"), list)


def wipe_stale_lvs_outputs(step: EccStep) -> None:
    """Remove native and published LVS outputs before a run so old reports cannot survive."""
    _unlink_file(optional_path(step.report.step))
    _unlink_file(optional_path(step.feature.step))
    reporter_dir = _lvs_reporter_dir(step)
    if reporter_dir is not None:
        _unlink_file(reporter_dir / "ilvs.rpt")
        _unlink_file(reporter_dir / "ilvs.json")


def copy_lvs_outputs(workspace: Workspace, step: EccStep) -> bool:
    """Publish LVS outputs; return True only when a fresh valid ilvs.json is copied."""
    report_target = optional_path(step.report.step)
    feature_target = optional_path(step.feature.step)
    _unlink_file(report_target)
    _unlink_file(feature_target)

    reporter_dir = _lvs_reporter_dir(step)
    if reporter_dir is None or not reporter_dir.is_dir():
        return False

    report_source = reporter_dir / "ilvs.rpt"
    if report_target is not None and report_source.is_file():
        report_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_source, report_target)
        workspace.logger.info("Copied LVS %s to %s", report_source, report_target)

    feature_source = reporter_dir / "ilvs.json"
    if feature_target is None or not feature_source.is_file():
        return False
    if not _has_valid_violations_payload(feature_source):
        return False

    feature_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(feature_source, feature_target)
    workspace.logger.info("Copied LVS %s to %s", feature_source, feature_target)
    return True
