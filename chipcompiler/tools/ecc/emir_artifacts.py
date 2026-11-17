"""Publication policy for iEMIR's native report artifacts."""

import hashlib
import json
import shutil
from pathlib import Path

EMIR_REPORTER_DIRECTORY = "emir_reporter"


def discard_ir_snapshot(data_dir: str | Path, geometry_manifest: str | Path) -> None:
    """Remove derived IR results before a rerun, including failed attempts."""
    root = Path(geometry_manifest).parent / "ir"
    for name in ("ir_drop.json", ".ir_drop.json.tmp"):
        (root / name).unlink(missing_ok=True)
    (Path(data_dir) / EMIR_REPORTER_DIRECTORY / "ir_drop.json").unlink(missing_ok=True)


def publish_ir_snapshot(data_dir: str | Path, geometry_manifest: str | Path) -> None:
    """Bind native structured IR samples to the just-saved geometry snapshot."""
    source = Path(data_dir) / EMIR_REPORTER_DIRECTORY / "ir_drop.json"
    if not source.is_file():
        return  # Older ecc-tools runtimes still publish their textual reports.
    manifest = Path(geometry_manifest)
    if not manifest.is_file():
        raise FileNotFoundError(f"EMIR geometry snapshot is missing: {manifest}")
    document = json.loads(source.read_text())
    fields = dict(line.split("=", 1) for line in manifest.read_text().splitlines() if "=" in line)
    if (
        document.get("schema") != "ecos.emir.ir.v1"
        or document.get("coordinate_unit") != "dbu"
        or document.get("dbu_per_micron") != int(fields["dbu_per_micron"])
    ):
        raise ValueError("IR spatial data and geometry have incompatible units")
    document["geometry_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    target = manifest.parent / "ir" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(document, separators=(",", ":"), allow_nan=False))
    temporary.replace(target)


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
