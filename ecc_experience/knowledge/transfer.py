"""Export selected evidence and merge fully validated experience packages."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from ecc_experience.files import canonical_bytes, case_identity, read_json, safe_child
from ecc_experience.knowledge.package_archive import (
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    PackageManifest,
    build_manifest,
    invalid,
    read_archive,
    write_archive,
)
from ecc_experience.knowledge.release import case_record, validate_release
from ecc_experience.knowledge.store import CASE_ID_PATTERN, ExperienceStore
from ecc_experience.models import CaseContents, ExperienceCase, ExperienceError


def export_package(
    store: str | Path,
    output: str | Path,
    *,
    case_ids: list[str] | None = None,
    release: str | Path | None = None,
) -> dict:
    if bool(case_ids) == (release is not None):
        raise ExperienceError(
            "Select either --case-id or --release", code="experience_package_selection_invalid"
        )
    repository = ExperienceStore(store)
    destination = Path(output).expanduser().absolute()
    if destination.resolve().is_relative_to(repository.root):
        raise ExperienceError(
            "Package output must be outside the source store",
            code="experience_package_selection_invalid",
        )
    release_payload = read_json(Path(release).expanduser()) if release is not None else None
    selected = (
        [record["case_id"] for record in validate_release(release_payload)]
        if release_payload is not None
        else list(case_ids or [])
    )
    if not 0 < len(selected) <= 10000 or len(set(selected)) != len(selected):
        raise ExperienceError(
            "Select between 1 and 10000 unique cases", code="experience_package_selection_invalid"
        )
    files: dict[str, bytes] = {}
    total = 0
    for case_id in sorted(selected):
        case = repository.read(case_id)
        directory = repository.case_directory(case_id)
        contents = {"case.json": canonical_bytes(case.model_dump())}
        for evidence in case.evidence:
            if evidence.stored_path is not None:
                source = safe_child(directory, evidence.stored_path)
                if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
                    raise invalid("Stored evidence is unavailable or oversized")
                with source.open("rb") as stream:
                    content = stream.read(MAX_FILE_BYTES + 1)
                if len(content) > MAX_FILE_BYTES:
                    raise invalid("Stored evidence exceeds the file size limit")
                contents[evidence.stored_path] = content
        for name, content in contents.items():
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise invalid("Selected evidence exceeds the package size limit")
            files[f"cases/{case_id}/{name}"] = content
    if release_payload is not None:
        files["release.json"] = canonical_bytes(release_payload)
    try:
        manifest = build_manifest(files, selected)
    except ValidationError as exc:
        raise invalid("Selected evidence exceeds package limits") from exc
    _validate_contents(manifest, files)
    status = write_archive(destination, manifest, files)
    return {
        "status": status,
        "package_id": manifest.package_id,
        "case_count": len(selected),
        "file_count": len(files),
        "output": str(destination),
        "integrity": "pass",
        "release_id": release_payload["release_id"] if release_payload else None,
    }


def import_package(package: str | Path, store: str | Path) -> dict:
    repository = ExperienceStore(store)
    package_path = Path(package).expanduser().absolute()
    if package_path.resolve().is_relative_to(repository.root):
        raise ExperienceError(
            "Package input must be outside the destination store",
            code="experience_package_selection_invalid",
        )
    manifest, files = read_archive(package_path)
    entries, release = _validate_contents(manifest, files)
    statuses = repository.put_many(entries, release=release)
    cases = [
        {"case_id": entry.case.case_id, "status": statuses[entry.case.case_id]} for entry in entries
    ]
    created = sum(record["status"] == "created" for record in cases)
    return {
        "status": "imported" if "created" in statuses.values() else "already_present",
        "package_id": manifest.package_id,
        "store": str(repository.root),
        "integrity": "pass",
        "case_count": len(cases),
        "created_count": created,
        "already_present_count": len(cases) - created,
        "cases": cases,
        "release": {
            "release_id": release["release_id"],
            "status": statuses[release["release_id"]],
            "path": str(repository.root / "releases" / f"{release['release_id']}.json"),
        }
        if release is not None
        else None,
        "source_verification": "not_performed",
    }


def _validate_contents(
    manifest: PackageManifest, files: dict[str, bytes]
) -> tuple[list[CaseContents], dict | None]:
    entries = []
    expected = {"release.json"} if manifest.release_path is not None else set()
    for case_id in manifest.case_ids:
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise invalid("Invalid packaged case ID")
        prefix = f"cases/{case_id}/"
        reference = f"{prefix}case.json"
        try:
            case = ExperienceCase.model_validate(json.loads(files[reference]))
            if case.case_id != case_id or case_identity(case.model_dump()) != case_id:
                raise invalid("Packaged case identity mismatch")
        except (KeyError, ValueError, UnicodeError, RecursionError) as exc:
            raise invalid(f"Invalid packaged case: {case_id}") from exc
        expected.add(reference)
        copies = {}
        for evidence in case.evidence:
            if evidence.stored_path is None:
                continue
            path = PurePosixPath(evidence.stored_path)
            if (
                len(path.parts) != 2
                or path.parts[0] != "evidence"
                or path.as_posix() != evidence.stored_path
            ):
                raise invalid("Unsupported packaged evidence path")
            stored = f"{prefix}{evidence.stored_path}"
            try:
                content = files[stored]
            except KeyError as exc:
                raise invalid("Packaged evidence is missing") from exc
            if (evidence.sha256, evidence.bytes) != (
                hashlib.sha256(content).hexdigest(),
                len(content),
            ):
                raise invalid("Packaged evidence does not match the case manifest")
            expected.add(stored)
            copies[evidence.stored_path] = content
        entries.append(CaseContents(case, copies))
    if expected != set(files):
        raise invalid("Package contains missing or undeclared case evidence")
    release = None
    if manifest.release_path is not None:
        try:
            release = json.loads(files["release.json"])
            if not isinstance(release, dict):
                raise ValueError("Release must be an object")
            records = validate_release(release)
            cases = {entry.case.case_id: entry.case for entry in entries}
            if set(cases) != {record["case_id"] for record in records}:
                raise invalid("Release case membership mismatch")
            for record in records:
                if record != case_record(
                    cases[record["case_id"]], {"status": "pass", "integrity": "pass"}
                ):
                    raise invalid("Release case metadata mismatch")
        except (ValueError, KeyError, UnicodeError, RecursionError) as exc:
            raise invalid("Invalid packaged release") from exc
    return entries, release
