"""Create a deterministic, path-redacted archive of campaign evidence."""

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.files import canonical_bytes


def create(manifest: str | Path, report: str | Path, output: str | Path) -> dict:
    _model, summary = load_manifest(manifest)
    report_root = Path(report).expanduser().resolve()
    destination = Path(output).expanduser().absolute()
    if not report_root.is_dir():
        raise ValueError("Campaign report directory does not exist")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Archive output must be new")
    protected = [Path(summary["manifest_root"]), Path(summary["output_root"]), report_root]
    if any(
        destination.resolve().is_relative_to(root) or root.is_relative_to(destination.resolve())
        for root in protected
    ):
        raise ValueError("Archive output must be outside campaign inputs and reports")
    files = {
        "campaign/campaign.json": _json_bytes(Path(summary["manifest"])),
    }
    output_root = Path(summary["output_root"])
    for name in ("campaign-ledger.json", "campaign-run.json"):
        path = output_root / name
        if path.is_file():
            files[f"campaign/{name}"] = _json_bytes(path)
    for path in sorted(report_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(report_root).as_posix()
        files[f"reports/{relative}"] = _content(path)
    if not any(name.startswith("reports/") for name in files):
        raise ValueError("Campaign report directory is empty")
    cases = _case_ids(files)
    index = {
        "schema": "ecc-experience-campaign-archive/1",
        "campaign_id": summary["campaign_id"],
        "manifest_fingerprint": summary["fingerprint"],
        "case_ids": sorted(cases),
        "redaction": "absolute paths in JSON values are replaced with <path-redacted>",
        "files": [],
    }
    for name, content in sorted(files.items()):
        index["files"].append(
            {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        )
    files["archive-index.json"] = canonical_bytes(index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination.open("xb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        for name, content in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o600
            member.mtime = 0
            archive.addfile(member, io.BytesIO(content))
    return {
        **index,
        "status": "created",
        "output": str(destination),
        "archive_sha256": _sha256(destination),
    }


def _json_bytes(path: Path) -> bytes:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid campaign JSON: {path}") from exc
    return canonical_bytes(_redact(value))


def _content(path: Path) -> bytes:
    if path.suffix.casefold() == ".json":
        return _json_bytes(path)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Unable to read campaign report: {path}") from exc


def _redact(value):
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        return "<path-redacted>"
    return value


def _case_ids(files: dict[str, bytes]) -> set[str]:
    result = set()
    for name, content in files.items():
        if not name.endswith(".json"):
            continue
        try:
            payload = json.loads(content)
        except (UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            if isinstance(payload.get("case_id"), str):
                result.add(payload["case_id"])
            for row in payload.get("rows", []):
                if isinstance(row, dict) and isinstance(row.get("case_id"), str):
                    result.add(row["case_id"])
    return result


def _sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()
