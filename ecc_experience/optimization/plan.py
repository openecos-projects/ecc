"""Build and persist conservative, human-reviewable optimization plans."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.files import canonical_bytes, digest
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.recommend import recommend
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.policy import OptimizationLimits


def build_plan(
    workspace: str | Path,
    store: str | Path,
    *,
    limit: int = 10,
    release: str | Path | None = None,
    optimization: OptimizationLimits | None = None,
    experimental_cross_design: bool = False,
    through_step: str | None = None,
    groups: str | Path | None = None,
    query_case_id: str | None = None,
) -> dict:
    if not experimental_cross_design and (through_step or groups or query_case_id):
        raise ExperienceError(
            "Cross-design query options require --experimental-cross-design",
            code="experience_plan_invalid",
        )
    if experimental_cross_design and release is None:
        raise ExperienceError(
            "Cross-design plans require a verified frozen release",
            code="experience_plan_invalid",
        )
    recommendation = recommend(workspace, store, limit=limit, release=release)
    query = recommendation["query"]
    candidates = recommendation["recommendations"]
    plan = {
        "schema_version": 1,
        "kind": "ecc-experience-optimization-plan",
        "created_at": datetime.now(UTC).isoformat(),
        "status": recommendation["status"],
        "query": query,
        "baseline": {
            "workspace": query["workspace"],
            "case_id": None,
            "snapshot_digest": read_workspace_observation(workspace).source.snapshot_digest,
        },
        "candidates": [
            {
                "candidate_id": f"observed-{index:04d}",
                "case_id": item["case_id"],
                "parameters": item["parameters"],
                "qor": item.get("qor", {}),
                "confidence": item["confidence"],
                "source": "exact_input",
                "safe_to_apply": False,
            }
            for index, item in enumerate(candidates, 1)
        ],
        "execution_policy": {
            "mode": "manual_review",
            "requires_new_workspace": True,
            "auto_apply": False,
            "requires_case_verification": True,
            "required_evidence": [
                "parameter_application_receipt",
                "committed_workspace_snapshot",
                "flow_and_checklist",
                "qor_and_signoff_reports",
            ],
        },
    }
    if not candidates:
        plan["reason"] = recommendation.get("reason", "No verified recommendation")
    if release is not None:
        plan["release_id"] = recommendation.get("release_verification", {}).get("release_id")
    if experimental_cross_design:
        if release is None:
            raise ExperienceError(
                "Cross-design plans require a verified frozen release",
                code="experience_plan_invalid",
            )
        cross_design, cross_candidates = _cross_design_candidates(
            recommendation,
            store,
            release=release,
            limit=limit,
            through_step=through_step,
            groups=groups,
            query_case_id=query_case_id,
        )
        plan["cross_design"] = cross_design
        seen = {item["case_id"] for item in plan["candidates"]}
        for item in cross_candidates:
            if item["case_id"] in seen:
                continue
            plan["candidates"].append(
                {
                    "candidate_id": f"cross-design-{len(plan['candidates']) + 1:04d}",
                    **item,
                    "safe_to_apply": False,
                }
            )
            seen.add(item["case_id"])
        plan["status"] = (
            "recommendations_available" if plan["candidates"] else "insufficient_evidence"
        )
        if plan["status"] == "insufficient_evidence":
            plan["reason"] = (
                "No verified cross-design candidate has applied parameter evidence; "
                "configured values remain review clues only"
            )
        elif not candidates:
            plan["reason"] = "Only opt-in experimental cross-design candidates are available"
    if optimization is not None:
        plan["optimization"] = optimization.checked().model_dump()
    identity = {key: value for key, value in plan.items() if key != "created_at"}
    plan["plan_fingerprint"] = digest(identity)
    return plan


def _cross_design_candidates(
    recommendation: dict,
    store: str | Path,
    *,
    release: str | Path,
    limit: int,
    through_step: str | None,
    groups: str | Path | None,
    query_case_id: str | None,
) -> tuple[dict, list[dict]]:
    fingerprint = recommendation["query"].get("input_content_fingerprint")
    block = {
        "requested": True,
        "safe_to_apply": False,
        "experimental_cross_design": True,
        "status": "insufficient_evidence",
        "confidence": "experimental",
        "query_case_id": None,
        "release_id": None,
        "through_step": through_step,
        "family_isolation": "explicit_groups" if groups else "not_checked",
        "matches": [],
        "clues": [],
        "limitations": [
            "Cross-design matches are experimental without independent calibrated benefit evidence",
            "Configured parameters are review clues, not executable cross-design candidates",
            "Any candidate still requires a new workspace and full plus fresh validation",
        ],
    }
    selected_id = _select_query_case(store, fingerprint, query_case_id)
    if selected_id is None:
        block["reason"] = "No committed query case matches the current input content"
        return block, []
    block["query_case_id"] = selected_id
    try:
        selected_through_step = through_step
        if selected_through_step is None:
            features = case_features(selected_id, store)
            steps = features.get("steps", [])
            if not steps:
                block["reason"] = "Query case has no visible flow step"
                return block, []
            step_name = steps[-1].get("step") if isinstance(steps[-1], dict) else None
            if not isinstance(step_name, str) or not step_name:
                block["reason"] = "Query case has no usable visible flow step"
                return block, []
            selected_through_step = step_name
            block["through_step"] = selected_through_step
        matched = match_cases(
            selected_id,
            store,
            release=release,
            through_step=selected_through_step,
            limit=limit,
            experimental_cross_design=True,
            groups=groups,
        )
    except ExperienceError as exc:
        block["reason"] = str(exc)
        return block, []
    block["release_id"] = matched.get("release_id")
    block["confidence"] = matched.get("confidence", "experimental")
    block["status"] = matched.get("status", "insufficient_evidence")
    if matched.get("reason"):
        block["reason"] = matched["reason"]
    candidates = []
    for item in matched.get("matches", []):
        if item.get("match_quality") != "compatible_design":
            continue
        parameters = item.get("parameters", {})
        values = parameters.get("values") if isinstance(parameters, dict) else None
        if not isinstance(values, dict) or not values:
            continue
        entry = {
            "case_id": item["case_id"],
            "match_quality": item["match_quality"],
            "confidence": item.get("confidence", "experimental"),
            "distance": item.get("distance"),
            "feature_coverage": item.get("feature_coverage"),
            "parameter_evidence_level": item.get("parameter_evidence_level", "unknown"),
            "parameters": values,
            "provenance": item.get("provenance", []),
        }
        block["matches"].append(entry)
        if entry["parameter_evidence_level"] != "applied":
            block["clues"].append(entry)
            continue
        candidates.append({**entry, "source": "compatible_design"})
    if block["status"] == "matches_available" and not block["matches"]:
        block["status"] = "insufficient_evidence"
        block["reason"] = "No compatible cross-design match is available"
    if block["status"] != "matches_available":
        block["reason"] = block.get("reason", "No compatible experimental cross-design match")
    return block, candidates


def _select_query_case(
    store: str | Path, fingerprint: str | None, query_case_id: str | None
) -> str | None:
    if fingerprint is None:
        return None
    repository = ExperienceStore(store)
    if not repository.root.is_dir():
        return None
    if query_case_id is not None:
        if not isinstance(query_case_id, str) or not query_case_id:
            raise ExperienceError("Query case ID is invalid", code="experience_plan_invalid")
        candidates = [query_case_id]
    else:
        candidates = list(reversed(repository.list_ids()))
    for case_id in candidates:
        try:
            case = repository.read(case_id)
        except ExperienceError as exc:
            if query_case_id is not None:
                raise ExperienceError(
                    "Query case is missing or invalid", code="experience_plan_invalid"
                ) from exc
            continue
        if case.input_content_fingerprint != fingerprint:
            if query_case_id is not None:
                raise ExperienceError(
                    "Query case does not belong to the current input content",
                    code="experience_plan_invalid",
                )
            continue
        if verify_case(case, repository.case_directory(case_id)).status == "fail":
            if query_case_id is not None:
                raise ExperienceError(
                    "Query case verification failed", code="experience_plan_invalid"
                )
            continue
        return case_id
    return None


def write_plan(path: str | Path, plan: dict) -> dict:
    destination = Path(path).expanduser().absolute()
    if destination.exists() and destination.is_symlink():
        raise ExperienceError("Plan output must not be a symlink", code="experience_plan_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{destination.name}.", dir=destination.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(canonical_bytes(plan))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"plan": str(destination.resolve()), **plan}
