"""Publication policy for iEMIR's native report artifacts."""

import shutil
from pathlib import Path

EMIR_REPORTER_DIRECTORY = "emir_reporter"


def publish_emir_reports(data_dir: str | Path, report_dir: str | Path) -> None:
    """Copy iEMIR's native reports into the step report directory."""
    reporter_dir = Path(data_dir) / EMIR_REPORTER_DIRECTORY
    if not reporter_dir.is_dir():
        raise FileNotFoundError(f"iEMIR report directory does not exist: {reporter_dir}")

    report_paths = sorted(path for path in reporter_dir.rglob("*") if path.is_file())
    if not report_paths:
        raise FileNotFoundError(f"iEMIR did not produce any reports in {reporter_dir}")

    report_root = Path(report_dir)
    for source_path in report_paths:
        target_path = report_root / source_path.relative_to(reporter_dir)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(f".{target_path.name}.tmp")
        shutil.copy2(source_path, temporary_path)
        temporary_path.replace(target_path)
