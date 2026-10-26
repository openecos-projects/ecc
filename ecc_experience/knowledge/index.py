"""Derived, rebuildable lookup index for large experience stores."""

from pathlib import Path

from ecc_experience.files import digest, read_json, safe_child
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError

INDEX_SCHEMA = "ecc-experience-store-index/1"
INDEX_RELATIVE = "index/cases.json"


def build_index(store: str | Path, output: str | Path | None = None) -> dict:
    from ecc_experience.optimization.plan import write_plan

    repository = ExperienceStore(store)
    if not repository.root.is_dir():
        raise ExperienceError("Experience store does not exist", code="experience_store_required")
    destination = (
        safe_child(repository.root, INDEX_RELATIVE)
        if output is None
        else Path(output).expanduser().absolute()
    )
    if not destination.is_relative_to(repository.root):
        raise ExperienceError(
            "The derived index must remain inside its source store",
            code="experience_index_invalid",
        )
    entries = []
    errors = []
    for case_id in repository.list_ids():
        try:
            case = repository.read(case_id)
            verification = verify_case(case, repository.case_directory(case_id))
            flow = case.facts.get("flow", {})
            steps = flow.get("steps", []) if isinstance(flow, dict) else []
            qor = case.facts.get("qorSnapshotExtension", {})
            qor_data = qor if isinstance(qor, dict) else {}
            entries.append(
                {
                    "case_id": case.case_id,
                    "schema_version": case.schema_version,
                    "design_fingerprint": case.design_fingerprint
                    or (case.design.fingerprint if case.design else None),
                    "constraints_fingerprint": (
                        case.constraints.fingerprint if case.constraints else None
                    ),
                    "input_content_fingerprint": case.input_content_fingerprint,
                    "process_fingerprint": case.process_fingerprint,
                    "toolchain_fingerprint": (
                        case.toolchain.runtime_fingerprint if case.toolchain else None
                    ),
                    "steps": [
                        step["name"]
                        for step in steps
                        if isinstance(step, dict) and isinstance(step.get("name"), str)
                    ],
                    "qor_status": qor_data.get("status"),
                    "qor_score": qor_data.get("score"),
                    "resource_scope": _resource_scope(steps),
                    "verification_status": verification.status,
                    "integrity": verification.integrity,
                    "evidence": {
                        "count": len(case.evidence),
                        "digest": digest([item.model_dump() for item in case.evidence]),
                    },
                }
            )
        except (ExperienceError, OSError) as exc:
            errors.append({"case_id": case_id, "reason": str(exc)})
    identity = {"schema": INDEX_SCHEMA, "entries": entries, "errors": errors}
    result = {
        **identity,
        "index_id": f"index-{digest(identity)}",
        "status": "pass" if not errors else "partial",
        "case_count": len(entries),
        "error_count": len(errors),
        "limitations": [
            "The index is a derived cache and never a source of truth",
            "Candidates selected by the index are still read and digest-verified",
            "A missing or damaged index falls back to a full store scan",
        ],
    }
    write_plan(destination, result)
    return {**result, "output": str(destination)}


def read_index(store: str | Path) -> dict:
    repository = ExperienceStore(store)
    try:
        path = safe_child(repository.root, INDEX_RELATIVE)
    except ExperienceError as exc:
        return {"status": "invalid", "reason": str(exc), "entries": []}
    if not path.is_file():
        return {"status": "missing", "reason": "Derived index is missing", "entries": []}
    try:
        payload = read_json(path, 64 * 1024 * 1024)
        _validate(payload)
    except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"status": "invalid", "reason": str(exc), "entries": []}
    return {
        "status": "valid",
        "index_id": payload["index_id"],
        "case_count": payload["case_count"],
        "entries": payload["entries"],
    }


def filter_case_ids(
    store: str | Path,
    case_ids: list[str],
    *,
    input_fingerprint: str | None = None,
    process_fingerprint: str | None = None,
    through_step: str | None = None,
) -> tuple[list[str], dict]:
    index = read_index(store)
    if index["status"] != "valid":
        return case_ids, index
    entries = {entry["case_id"]: entry for entry in index["entries"]}
    selected = []
    for case_id in case_ids:
        entry = entries.get(case_id)
        if entry is None:
            selected.append(case_id)
            continue
        if (
            input_fingerprint is not None
            and isinstance(entry.get("input_content_fingerprint"), str)
            and entry["input_content_fingerprint"] != input_fingerprint
        ):
            continue
        if (
            process_fingerprint is not None
            and isinstance(entry.get("process_fingerprint"), str)
            and entry["process_fingerprint"] != process_fingerprint
        ):
            continue
        steps = entry.get("steps")
        if through_step is not None and isinstance(steps, list) and through_step not in steps:
            continue
        selected.append(case_id)
    return selected, {**index, "status": "used"}


def index_status(store: str | Path) -> dict:
    index = read_index(store)
    return {key: value for key, value in index.items() if key != "entries"} | {
        "entry_count": len(index["entries"])
    }


def _validate(payload: dict) -> None:
    entries = payload.get("entries")
    errors = payload.get("errors")
    if (
        payload.get("schema") != INDEX_SCHEMA
        or not isinstance(entries, list)
        or not isinstance(errors, list)
        or payload.get("case_count") != len(entries)
        or payload.get("error_count") != len(errors)
        or payload.get("index_id")
        != f"index-{digest({'schema': INDEX_SCHEMA, 'entries': entries, 'errors': errors})}"
    ):
        raise ExperienceError("Invalid derived experience index", code="experience_index_invalid")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("case_id"), str)
            or not isinstance(entry.get("steps"), list)
            or not all(isinstance(step, str) for step in entry["steps"])
            or not isinstance(entry.get("evidence"), dict)
        ):
            raise ExperienceError("Invalid derived index entry", code="experience_index_invalid")


def _resource_scope(steps: list) -> dict:
    scopes = []
    for step in steps:
        observation = step.get("resource_observation") if isinstance(step, dict) else None
        if not isinstance(observation, dict):
            continue
        host = observation.get("host") if isinstance(observation.get("host"), dict) else {}
        concurrency = (
            observation.get("concurrency")
            if isinstance(observation.get("concurrency"), dict)
            else {}
        )
        scopes.append(
            {
                "step": step.get("name"),
                "scope": observation.get("scope"),
                "host_class": host.get("class") or host.get("cpu_model"),
                "max_concurrent": concurrency.get("max_concurrent"),
            }
        )
    return {"steps": scopes}
