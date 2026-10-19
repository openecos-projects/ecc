"""Promote verified positive selections from a normalized manifest."""

from pathlib import Path
from typing import Any

from ecc_experience.files import digest, read_json, safe_child
from ecc_experience.knowledge.release import create_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.summary import summarize_case
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import CaseContents, ExperienceError

NORMALIZED_SCHEMA = "ecc-experience-normalized-manifest/1"
_MANIFEST_KEYS = {
    "schema",
    "status",
    "exit_code",
    "counts",
    "stores",
    "cases",
    "configuration_groups",
    "selections",
    "errors",
    "limitations",
    "manifest_id",
}
_SELECTION_KEYS = {"positive", "negative", "qor_missing", "other", "quarantine"}


def release_from_manifest(
    manifest: str | Path, store: str | Path, output: str | Path
) -> dict[str, Any]:
    payload = _read_manifest(manifest)
    selections = _positive_selections(payload)
    source_repositories = _source_repositories(payload)
    destination = ExperienceStore(store)
    output_path = Path(output).expanduser()
    resolved_output = output_path.resolve()
    _check_boundaries(source_repositories, destination, output_path, resolved_output)

    entries = []
    included = []
    excluded = []
    for reference in selections:
        case_id = reference["case_id"]
        repository = source_repositories[reference["store"]]
        try:
            _validate_reference_path(repository, reference)
            case = repository.read(case_id)
            verification = verify_case(case, repository.case_directory(case_id))
            summary = summarize_case(case, verification)
            if verification.status != "pass" or verification.integrity != "pass":
                raise ExperienceError(
                    f"Current verification is {verification.status}/{verification.integrity}"
                )
            if not summary["release_eligible"]:
                raise ExperienceError("Current case is not release eligible")
            copies = _evidence_copies(case, repository.case_directory(case_id))
        except (ExperienceError, OSError) as exc:
            excluded.append(
                {
                    "case_id": case_id,
                    "store": reference["store"],
                    "status": "excluded",
                    "reason": str(exc),
                }
            )
            continue
        entries.append(CaseContents(case, copies))
        included.append({"case_id": case_id, "store": reference["store"]})

    base = {
        "manifest": str(Path(manifest).expanduser().resolve()),
        "manifest_id": payload["manifest_id"],
        "destination_store": str(destination.root),
        "selected_count": len(selections),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included": included,
        "excluded": excluded,
        "selection_status": "complete" if not excluded else "partial",
    }
    if not entries:
        return {
            **base,
            "status": "unknown",
            "release_created": False,
            "release_id": None,
            "case_count": 0,
            "exit_code": 7,
        }

    if resolved_output.exists() or output_path.is_symlink():
        raise ExperienceError("Release output already exists", code="experience_release_conflict")
    destination.put_many(entries)
    release = create_release(
        [entry.case.case_id for entry in entries], destination.root, output_path
    )
    return {
        **base,
        **release,
        "release_created": True,
        "exit_code": 7 if excluded else 0,
    }


def _read_manifest(path: str | Path) -> dict[str, Any]:
    try:
        payload = read_json(Path(path).expanduser())
    except (ExperienceError, OSError) as exc:
        raise ExperienceError(
            f"Cannot read normalized experience manifest: {exc}",
            code="experience_release_manifest_invalid",
        ) from exc
    if set(payload) != _MANIFEST_KEYS or payload.get("schema") != NORMALIZED_SCHEMA:
        raise ExperienceError(
            "Invalid normalized experience manifest", code="experience_release_manifest_invalid"
        )
    identity = {key: value for key, value in payload.items() if key != "manifest_id"}
    if payload.get("manifest_id") != f"normalized-{digest(identity)}":
        raise ExperienceError(
            "Normalized manifest identity mismatch",
            code="experience_release_manifest_invalid",
        )
    selections = payload.get("selections")
    if not isinstance(selections, dict) or set(selections) != _SELECTION_KEYS:
        raise ExperienceError(
            "Invalid normalized manifest selections",
            code="experience_release_manifest_invalid",
        )
    stores = payload.get("stores")
    if (
        not isinstance(stores, list)
        or not stores
        or any(
            not isinstance(source, dict)
            or set(source) != {"store", "cases", "changed_during_read"}
            or not isinstance(source["store"], str)
            for source in stores
        )
    ):
        raise ExperienceError(
            "Invalid normalized manifest stores",
            code="experience_release_manifest_invalid",
        )
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ExperienceError(
            "Invalid normalized manifest cases", code="experience_release_manifest_invalid"
        )
    available = {
        (case.get("case_id"), provenance.get("store"), provenance.get("case_path"))
        for case in cases
        if isinstance(case, dict)
        for provenance in case.get("provenance", [])
        if isinstance(provenance, dict)
    }
    for category, values in selections.items():
        if not isinstance(values, list):
            raise ExperienceError(
                f"Invalid normalized manifest selection: {category}",
                code="experience_release_manifest_invalid",
            )
        if category == "positive":
            for reference in values:
                if (
                    not isinstance(reference, dict)
                    or set(reference) != {"case_id", "store", "case_path"}
                    or not all(isinstance(reference[key], str) for key in reference)
                    or (reference["case_id"], reference["store"], reference["case_path"])
                    not in available
                ):
                    raise ExperienceError(
                        "Invalid normalized manifest positive selection",
                        code="experience_release_manifest_invalid",
                    )
    return payload


def _positive_selections(payload: dict[str, Any]) -> list[dict[str, str]]:
    selections = payload["selections"]["positive"]
    if len({reference["case_id"] for reference in selections}) != len(selections):
        raise ExperienceError(
            "Normalized manifest positive selection contains duplicates",
            code="experience_release_manifest_invalid",
        )
    return selections


def _source_repositories(payload: dict[str, Any]) -> dict[str, ExperienceStore]:
    repositories = {}
    try:
        for source in payload["stores"]:
            repository = ExperienceStore(source["store"])
            if str(repository.root) != source["store"]:
                raise ExperienceError("Normalized manifest store path is not canonical")
            repositories[source["store"]] = repository
    except (ExperienceError, OSError) as exc:
        raise ExperienceError(
            f"Cannot open normalized manifest source store: {exc}",
            code="experience_release_manifest_invalid",
        ) from exc
    return repositories


def _check_boundaries(
    sources: dict[str, ExperienceStore],
    destination: ExperienceStore,
    output: Path,
    resolved_output: Path,
) -> None:
    for source in sources.values():
        if (
            destination.root == source.root
            or destination.root.is_relative_to(source.root)
            or source.root.is_relative_to(destination.root)
        ):
            raise ExperienceError(
                "Release destination must be an independent store",
                code="experience_release_manifest_invalid",
            )
        if resolved_output.is_relative_to(source.root):
            raise ExperienceError(
                "Release output must be outside source stores",
                code="experience_release_manifest_invalid",
            )
    if resolved_output.is_relative_to(destination.root):
        raise ExperienceError(
            "Release output must be outside the destination store",
            code="experience_release_manifest_invalid",
        )
    if output.is_symlink():
        raise ExperienceError(
            "Release output must not be a symlink", code="experience_release_invalid"
        )


def _validate_reference_path(repository: ExperienceStore, reference: dict[str, str]) -> None:
    expected = repository.case_directory(reference["case_id"]) / "case.json"
    actual = Path(reference["case_path"]).expanduser().resolve()
    if actual != expected.resolve():
        raise ExperienceError("Manifest provenance path does not match the case")


def _evidence_copies(case: Any, case_directory: Path) -> dict[str, bytes]:
    copies = {}
    for evidence in case.evidence:
        if evidence.stored_path is None:
            continue
        path = safe_child(case_directory, evidence.stored_path)
        copies[evidence.stored_path] = path.read_bytes()
    return copies
