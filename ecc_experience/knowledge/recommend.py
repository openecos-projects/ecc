"""Conservative, read-only retrieval of observed configurations."""

import re
from pathlib import Path
from typing import Any

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.adapters.input_closure import content_fingerprint
from ecc_experience.knowledge.index import filter_case_ids
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError, InputDigest, parameter_evidence_level


def recommend(
    workspace: str | Path,
    store: str | Path,
    *,
    limit: int = 10,
    release: str | Path | None = None,
) -> dict:
    if limit < 1 or limit > 100:
        raise ExperienceError("Recommendation limit must be between 1 and 100")
    observation = read_workspace_observation(workspace)
    fingerprint = _input_fingerprint(observation.facts, observation.inputs)
    result = {
        "status": "insufficient_evidence",
        "query": {
            "workspace": str(Path(workspace).expanduser().resolve()),
            "input_content_fingerprint": fingerprint,
            "match_policy": "same_input_content_only",
            "release": str(Path(release).expanduser().resolve()) if release else None,
        },
        "candidates": [],
        "recommendations": [],
    }
    if fingerprint is None:
        result["reason"] = "Query workspace has no complete input content fingerprint"
        return result

    allowed_case_ids = None
    if release is not None:
        release_result = verify_release(release, store)
        result["release_verification"] = release_result
        if release_result["status"] != "pass":
            result["reason"] = "Experience release verification did not pass"
            return result
        allowed_case_ids = {
            item["case_id"] for item in release_result["cases"] if item["status"] == "pass"
        }

    repository = ExperienceStore(store)
    if not repository.root.is_dir():
        result["reason"] = "Experience store does not exist"
        return result
    ordered = list(reversed(repository.list_ids()))
    if allowed_case_ids is not None:
        ordered = [case_id for case_id in ordered if case_id in allowed_case_ids]
    ordered, index = filter_case_ids(
        repository.root,
        ordered,
        input_fingerprint=fingerprint,
    )
    result["index"] = index
    for case_id in ordered:
        case = repository.read(case_id)
        if case.input_content_fingerprint != fingerprint:
            continue
        verification = verify_case(case, repository.case_directory(case_id))
        candidate = {
            "case_id": case.case_id,
            "collected_at": case.collected_at,
            "verification_status": verification.status,
            "integrity": verification.integrity,
            "parameter_evidence": case.parameter_evidence.model_dump()
            if not isinstance(case.parameter_evidence, str)
            else case.parameter_evidence,
            "parameter_evidence_level": parameter_evidence_level(case),
            "limitations": case.limitations,
            "qor": _qor_summary(case.facts),
            "release": str(Path(release).expanduser().resolve()) if release else None,
        }
        result["candidates"].append(candidate)
        parameters = _configured_parameters(case.facts)
        if verification.status == "fail" or parameters is None:
            continue
        result["recommendations"].append(
            {
                "kind": "observed_configuration",
                "case_id": case.case_id,
                "confidence": "observed_only",
                "safe_to_apply": False,
                "parameters": parameters,
                "qor": candidate["qor"],
                "verification_status": verification.status,
                "reason": "Review and validate this configuration before applying it",
            }
        )
        if len(result["recommendations"]) >= limit:
            break
    result["candidates"] = result["candidates"][:limit]
    if result["recommendations"]:
        result["status"] = "recommendations_available"
    else:
        result["reason"] = "No verified observed configuration is available for this input"
    return result


def _input_fingerprint(facts: dict, inputs: list[InputDigest]) -> str | None:
    return content_fingerprint(facts, inputs)


def _configured_parameters(facts: dict) -> dict | None:
    specification = facts.get("workspaceSpec", {})
    if not isinstance(specification, dict):
        return None
    parameters = specification.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        return None
    sanitized = _sanitize(parameters)
    return sanitized if isinstance(sanitized, dict) else None


def _qor_summary(facts: dict) -> dict:
    qor = facts.get("qorSnapshotExtension")
    if not isinstance(qor, dict):
        return {}
    return {key: qor[key] for key in ("score", "status", "reason", "source") if key in qor}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and _is_absolute_path(value):
        return "<path-redacted>"
    return value


def _is_absolute_path(value: str) -> bool:
    return value.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", value))
