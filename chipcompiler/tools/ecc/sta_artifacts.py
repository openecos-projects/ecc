"""Publication policy for iSTA run artifacts.

iSTA writes timing reports to ``<work_dir>/timing_reporter`` and the SDF to
``<work_dir>/sdf_writer``. This module validates those outputs and publishes
them to the per-corner report/feature directories.
"""

import shutil
from pathlib import Path

STA_REQUIRED_STRUCTURED_FILENAMES = ("qor_summary.json",)


def copy_sta_artifact(source_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target_path = destination_dir / source_path.name
    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    shutil.copy2(source_path, temporary_path)
    temporary_path.replace(target_path)


def clear_published_sdf(report_dir: str | Path) -> None:
    """Drop previously published SDF files so a failed rerun cannot expose them as current."""
    for stale_sdf in Path(report_dir).glob("*.sdf"):
        stale_sdf.unlink()


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

    if "report" in modes:
        report_root = Path(report_dir)
        for source_path in report_paths:
            copy_sta_artifact(source_path, report_root)
        for sdf_path in sdf_paths:
            copy_sta_artifact(sdf_path, report_root)
    if "structured" in modes:
        feature_root = Path(feature_dir)
        for source_path in structured_paths:
            copy_sta_artifact(source_path, feature_root)
