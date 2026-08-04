"""Publication policy for iSTA run artifacts.

iSTA writes timing reports to ``<work_dir>/timing_reporter``, the power
report to ``<work_dir>/power_reporter`` and the SDF to
``<work_dir>/sdf_writer``. This module validates those outputs and publishes
them to the per-corner report/feature directories.
"""

import shutil
from pathlib import Path

from chipcompiler.tools.ecc.sta_qor import (
    STA_POWER_REPORT_FILENAME,
    STA_POWER_SUMMARY_FILENAME,
    read_sta_power_summary,
    sta_power_summary_payload,
)
from chipcompiler.utility import json_write

STA_REQUIRED_STRUCTURED_FILENAMES = ("qor_summary.json",)


def copy_sta_artifact(source_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target_path = destination_dir / source_path.name
    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    shutil.copy2(source_path, temporary_path)
    temporary_path.replace(target_path)


def discard_sta_outputs(directory) -> None:
    # Remove every artifact an STA run publishes into a destination directory,
    # so a failed rerun cannot leave previous outputs visible as current.
    # Report names vary with iSTA's start_end_type config, hence the glob.
    root = Path(directory) if directory else None
    if root is None or not root.is_dir():
        return
    for pattern in ("*.rpt", "*.json", "*.sdf"):
        for stale_path in root.glob(pattern):
            if stale_path.is_file():
                stale_path.unlink()


def discard_sta_run_outputs(work_dir, report_dir, feature_dir, modes) -> None:
    # Invalidate every artifact the STA run can republish: stale temp outputs
    # must not mask a failed native run, and previously published copies must
    # not survive a failed rerun. Only destinations whose mode was requested
    # are cleared; unrequested modes are not republished and keep their copies.
    work_root = Path(work_dir)
    power_report_path = work_root / "power_reporter" / STA_POWER_REPORT_FILENAME
    power_report_path.unlink(missing_ok=True)
    for temp_subdirectory in ("timing_reporter", "sdf_writer"):
        temp_dir = work_root / temp_subdirectory
        if temp_dir.is_dir():
            for stale_path in temp_dir.iterdir():
                if stale_path.is_file():
                    stale_path.unlink()
    if "report" in modes:
        discard_sta_outputs(report_dir)
    if "structured" in modes:
        discard_sta_outputs(feature_dir)


def publish_sta_artifacts(
    work_dir: str | Path,
    report_dir: str | Path,
    feature_dir: str | Path,
    modes: tuple[str, ...],
) -> None:
    """Validate iSTA outputs under work_dir and copy them to the corner directories."""
    timing_report_dir = Path(work_dir) / "timing_reporter"
    if not timing_report_dir.is_dir():
        raise FileNotFoundError(
            f"iSTA timing reporter output directory does not exist: {timing_report_dir}"
        )

    source_paths = [path for path in timing_report_dir.iterdir() if path.is_file()]
    report_paths = [path for path in source_paths if path.suffix != ".json"]
    structured_paths = [path for path in source_paths if path.suffix == ".json"]

    # Validate every requested mode before mutating any destination, so a
    # failed run cannot leave a partially updated artifact set behind.
    sdf_paths: list[Path] = []
    if "report" in modes:
        if not report_paths:
            raise FileNotFoundError("iSTA did not produce requested text reports")
        sdf_paths = sorted((Path(work_dir) / "sdf_writer").glob("*.sdf"))
        if not sdf_paths:
            raise FileNotFoundError(
                f"iSTA did not produce an SDF file in {Path(work_dir) / 'sdf_writer'}"
            )
    if "structured" in modes:
        names = {path.name for path in structured_paths}
        missing = [name for name in STA_REQUIRED_STRUCTURED_FILENAMES if name not in names]
        if missing:
            raise FileNotFoundError(
                f"iSTA did not produce requested structured artifacts: {', '.join(missing)}"
            )
    power_report_path = Path(work_dir) / "power_reporter" / STA_POWER_REPORT_FILENAME
    if not power_report_path.is_file():
        raise FileNotFoundError(f"iSTA power report does not exist: {power_report_path}")
    # The structured destination holds machine-readable artifacts only, so the
    # plaintext power report is converted to a JSON summary. Parse before
    # publishing anything: the artifact set publishes all at once.
    power_summary_payload = None
    if "structured" in modes:
        power_summary = read_sta_power_summary(power_report_path)
        if power_summary is None:
            raise ValueError(f"iSTA power report is not parseable: {power_report_path}")
        power_summary_payload = sta_power_summary_payload(power_summary)

    try:
        if "report" in modes:
            report_root = Path(report_dir)
            for source_path in report_paths:
                copy_sta_artifact(source_path, report_root)
            for sdf_path in sdf_paths:
                copy_sta_artifact(sdf_path, report_root)
            copy_sta_artifact(power_report_path, report_root)
        if "structured" in modes:
            feature_root = Path(feature_dir)
            for source_path in structured_paths:
                copy_sta_artifact(source_path, feature_root)
            power_summary_path = feature_root / STA_POWER_SUMMARY_FILENAME
            if not json_write(power_summary_path, power_summary_payload):
                raise OSError(f"Failed to write STA power summary: {power_summary_path}")
    except Exception:
        # Publication is all-or-nothing: a partial set left behind by a
        # failed run must not remain visible as current artifacts.
        if "report" in modes:
            discard_sta_outputs(report_dir)
        if "structured" in modes:
            discard_sta_outputs(feature_dir)
        raise
