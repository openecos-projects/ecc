"""Create and verify immutable, evidence-backed experience releases."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ecc_experience.files import canonical_bytes, digest, read_json
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError

RELEASE_SCHEMA = "ecc-experience-release/1"
_MAX_CASES = 10000


def create_release(case_ids: list[str], store: str | Path, output: str | Path) -> dict[str, Any]:
    selected = sorted(set(case_ids))
    if not selected or len(selected) > _MAX_CASES:
        raise ExperienceError(
            "A release requires between 1 and 10000 case IDs",
            code="experience_release_invalid",
        )
    if len(selected) != len(case_ids):
        raise ExperienceError(
            "Release case IDs must be unique", code="experience_release_invalid"
        )

    repository = ExperienceStore(store)
    cases = []
    for case_id in selected:
        case = repository.read(case_id)
        verification = verify_case(case, repository.case_directory(case_id))
        if verification.status != "pass" or verification.integrity != "pass":
            raise ExperienceError(
                f"Case is not verified: {case_id}", code="experience_release_unverified"
            )
        if case.input_content_fingerprint is None:
            raise ExperienceError(
                f"Case has no complete input fingerprint: {case_id}",
                code="experience_release_invalid",
            )
        cases.append(_case_record(case, verification.model_dump()))

    identity = {"schema": RELEASE_SCHEMA, "cases": cases}
    release = {
        **identity,
        "release_id": f"release-{digest(identity)}",
        "created_at": datetime.now(UTC).isoformat(),
        "policy": {
            "requires_verified_cases": True,
            "requires_complete_input_fingerprint": True,
            "auto_apply": False,
        },
    }
    status = _write_once(Path(output).expanduser(), release)
    return {
        "status": status,
        "release_id": release["release_id"],
        "case_count": len(cases),
        "output": str(Path(output).expanduser().resolve()),
    }


def verify_release(release_path: str | Path, store: str | Path) -> dict[str, Any]:
    payload = read_json(Path(release_path).expanduser())
    cases = _validate_release(payload)
    repository = ExperienceStore(store)
    records = []
    for record in cases:
        case_id = record["case_id"]
        try:
            case = repository.read(case_id)
            verification = verify_case(case, repository.case_directory(case_id))
            matches = (
                case.input_content_fingerprint == record["input_content_fingerprint"]
                and case.source.workspace_id == record["workspace_id"]
                and case.source.workspace_revision == record["workspace_revision"]
            )
            records.append(
                {
                    "case_id": case_id,
                    "status": verification.status if matches else "fail",
                    "integrity": verification.integrity if matches else "fail",
                    "release_record_matches": matches,
                }
            )
        except (ExperienceError, OSError) as exc:
            records.append(
                {
                    "case_id": case_id,
                    "status": "fail",
                    "integrity": "fail",
                    "release_record_matches": False,
                    "reason": str(exc),
                }
            )
    statuses = {record["status"] for record in records}
    result_status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return {
        "release_id": payload["release_id"],
        "status": result_status,
        "case_count": len(records),
        "cases": records,
    }


def _case_record(case: Any, verification: dict[str, Any]) -> dict[str, Any]:
    qor = case.facts.get("qorSnapshotExtension")
    score = qor.get("score") if isinstance(qor, dict) else None
    return {
        "case_id": case.case_id,
        "input_content_fingerprint": case.input_content_fingerprint,
        "design_fingerprint": case.design_fingerprint,
        "process_fingerprint": case.process_fingerprint,
        "workspace_id": case.source.workspace_id,
        "workspace_revision": case.source.workspace_revision,
        "qor_score": score,
        "verification": {
            "status": verification["status"],
            "integrity": verification["integrity"],
        },
    }


def _validate_release(payload: dict[str, Any]) -> list[dict[str, Any]]:
    required = {"schema", "cases", "release_id", "created_at", "policy"}
    if set(payload) != required or payload.get("schema") != RELEASE_SCHEMA:
        raise ExperienceError("Invalid experience release", code="experience_release_invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 0 < len(cases) <= _MAX_CASES:
        raise ExperienceError("Invalid experience release cases", code="experience_release_invalid")
    identity = {"schema": RELEASE_SCHEMA, "cases": cases}
    if payload.get("release_id") != f"release-{digest(identity)}":
        raise ExperienceError(
            "Experience release identity mismatch", code="experience_release_invalid"
        )
    if payload.get("policy") != {
        "requires_verified_cases": True,
        "requires_complete_input_fingerprint": True,
        "auto_apply": False,
    }:
        raise ExperienceError(
            "Invalid experience release policy", code="experience_release_invalid"
        )
    required_case = {
        "case_id",
        "input_content_fingerprint",
        "design_fingerprint",
        "process_fingerprint",
        "workspace_id",
        "workspace_revision",
        "qor_score",
        "verification",
    }
    for case in cases:
        if not isinstance(case, dict) or set(case) != required_case:
            raise ExperienceError(
                "Invalid experience release case", code="experience_release_invalid"
            )
        if not isinstance(case["case_id"], str) or not isinstance(
            case["input_content_fingerprint"], str
        ):
            raise ExperienceError(
                "Invalid experience release case identity", code="experience_release_invalid"
            )
        if case["verification"] != {"status": "pass", "integrity": "pass"}:
            raise ExperienceError(
                "Release contains an unverified case", code="experience_release_invalid"
            )
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ExperienceError(
            "Experience release contains duplicate cases", code="experience_release_invalid"
        )
    return cases


def _write_once(path: Path, payload: dict[str, Any]) -> str:
    if path.is_symlink():
        raise ExperienceError(
            "Release output must not be a symlink", code="experience_release_invalid"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(payload)
    if path.exists():
        existing = read_json(path)
        existing.pop("created_at", None)
        expected = dict(payload)
        expected.pop("created_at", None)
        if existing == expected:
            return "already_present"
        raise ExperienceError("Release output already exists", code="experience_release_conflict")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"
