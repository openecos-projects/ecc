"""Explain frozen-release matches without inferring unsupported generalization."""

from pathlib import Path

from ecc_experience.files import read_json
from ecc_experience.knowledge.budget import resource_budget
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.index import filter_case_ids
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.similarity import (
    MIN_FEATURE_COVERAGE,
    SIMILARITY_SCHEMA,
    feature_distance,
    parameter_ranges,
    stage_features,
)
from ecc_experience.models import ExperienceError


def match_cases(
    case_id: str,
    store: str | Path,
    *,
    release: str | Path,
    through_step: str,
    limit: int = 10,
    experimental_cross_design: bool = False,
    groups: str | Path | None = None,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ExperienceError("Match limit must be between 1 and 100")
    query = case_features(case_id, store, through_step=through_step)
    frozen = verify_release(release, store)
    families = read_groups(groups) if groups else {}
    result = {
        "schema": "ecc-experience-similar-designs/1",
        "feature_schema": SIMILARITY_SCHEMA,
        "status": "insufficient_evidence",
        "match_quality": "insufficient_evidence",
        "query_case_id": case_id,
        "through_step": through_step,
        "release_id": frozen["release_id"],
        "release_verification": frozen,
        "experimental_cross_design": experimental_cross_design,
        "family_isolation": "explicit_groups" if groups else "not_checked",
        "safe_to_apply": False,
        "parameter_ranges": {},
        "matches": [],
        "excluded": [],
        "limitations": [
            "A match is an observed configuration, not evidence of a causal parameter effect",
            "Cross-design distance is experimental and has no calibrated benefit confidence",
            "Selected PDK hashes and observed tool versions do not prove full dependency closure",
            "Missing execution, process or analysis identities exclude a candidate",
            "A feature match is similarity, not a causal parameter effect",
        ],
    }
    if frozen["status"] != "pass" or query["status"] == "fail":
        result["reason"] = "Release or query evidence did not pass verification"
        return result
    records = frozen["cases"]
    ordered_ids, index = filter_case_ids(
        store,
        [record["case_id"] for record in records],
        process_fingerprint=query.get("process_fingerprint"),
        through_step=through_step,
    )
    selected = set(ordered_ids)
    records = [
        record
        for record in records
        if record["case_id"] in selected or record["case_id"] == case_id
    ]
    result["index"] = index
    query_stage = query["steps"][-1]
    query_features = stage_features(query)
    for record in records:
        candidate_id = record["case_id"]
        if candidate_id == case_id:
            result["excluded"].append({"case_id": candidate_id, "reasons": ["query_case_itself"]})
            continue
        try:
            candidate = case_features(candidate_id, store, through_step=through_step)
        except ExperienceError:
            result["excluded"].append({"case_id": candidate_id, "reasons": ["stage_unavailable"]})
            continue
        stage = candidate["steps"][-1]
        reasons = compatibility_reasons(query, candidate, query_stage, stage)
        same_inputs = (
            query["input_content_fingerprint"] is not None
            and query["input_content_fingerprint"] == candidate["input_content_fingerprint"]
        )
        if not same_inputs and not experimental_cross_design:
            reasons.append("cross_design_not_enabled")
        if not same_inputs and (
            query.get("schema_version") == 1 or candidate.get("schema_version") == 1
        ):
            reasons.append("cross_design_identity_v1")
        if groups:
            if not families.get(case_id) or not families.get(candidate_id):
                reasons.append("family_unknown")
            elif families[case_id] == families[candidate_id]:
                reasons.append("same_evaluation_group")
        distance, coverage, common = feature_distance(query_features, stage_features(candidate))
        if distance is None:
            reasons.append("no_comparable_structural_features")
        elif coverage < MIN_FEATURE_COVERAGE:
            reasons.append("insufficient_feature_coverage")
        if reasons:
            result["excluded"].append({"case_id": candidate_id, "reasons": reasons})
            continue
        result["matches"].append(
            {
                "case_id": candidate_id,
                "confidence": "observed_only" if same_inputs else "experimental",
                "confidence_class": "observed" if same_inputs else "experimental",
                "match_quality": "exact_input" if same_inputs else "compatible_design",
                "same_input_content": same_inputs,
                "distance": distance,
                "feature_coverage": coverage,
                "feature_schema": SIMILARITY_SCHEMA,
                "common_features": common,
                "parameters": candidate["parameters"],
                "parameter_evidence_level": candidate["parameters"].get("level", "unknown"),
                "safe_to_apply": False,
                "compatibility": "selected_process_tool_analysis_match",
                "provenance": [
                    {
                        "release_id": frozen["release_id"],
                        "case_id": candidate_id,
                        "distance": distance,
                        "feature_coverage": coverage,
                        "confidence": "observed" if same_inputs else "experimental",
                    }
                ],
            }
        )
    result["matches"].sort(key=lambda item: (item["distance"], item["case_id"]))
    result["matches"] = result["matches"][:limit]
    if result["matches"]:
        result["status"] = "matches_available"
        result["match_quality"] = (
            "exact_input"
            if all(item["match_quality"] == "exact_input" for item in result["matches"])
            else "compatible_design"
        )
        result["confidence"] = (
            "observed" if result["match_quality"] == "exact_input" else "experimental"
        )
        result["parameter_ranges"] = parameter_ranges(result["matches"])
    else:
        result["reason"] = "No compatible observed stage configuration in the frozen release"
    try:
        result["resource_budget"] = resource_budget(
            case_id,
            store,
            release=release,
            through_step=through_step,
        )
    except ExperienceError as exc:
        result["resource_budget"] = {
            "schema": "resource-budget/1",
            "status": "unknown",
            "reason": str(exc),
        }
    return result


def compatibility_reasons(query: dict, candidate: dict, left: dict, right: dict) -> list[str]:
    reasons = []
    for key in ("process", "process_fingerprint"):
        if not query.get(key) or not candidate.get(key):
            reasons.append(f"{key}_unknown")
        elif query[key] != candidate[key]:
            reasons.append(f"{key}_mismatch")
    for key in ("tool_identity", "analysis_revision", "analysis_context"):
        if not left.get(key) or not right.get(key):
            reasons.append(f"{key}_unknown")
        elif left[key] != right[key]:
            reasons.append(f"{key}_mismatch")
    for stage in (left, right):
        context = stage.get("analysis_context")
        constraints = context.get("timing_constraints") if isinstance(context, dict) else None
        if (
            not isinstance(constraints, dict) or not constraints.get("sdc_sha256")
        ) and "timing_constraints_unknown" not in reasons:
            reasons.append("timing_constraints_unknown")
    if candidate["status"] == "fail" or left["state"] != "Success" or right["state"] != "Success":
        reasons.append("stage_not_successful")
    return reasons


def feature_distance_legacy(left: dict, right: dict) -> tuple[float | None, list[dict]]:
    """Compatibility helper for callers that still hold one stage directly."""
    distance, _coverage, common = feature_distance(
        stage_features({"steps": [left]}), stage_features({"steps": [right]})
    )
    return distance, common


def read_groups(path: str | Path) -> dict[str, str]:
    payload = read_json(Path(path).expanduser(), 1024 * 1024)
    cases = payload.get("cases")
    if (
        set(payload) != {"schema_version", "cases"}
        or payload.get("schema_version") != 1
        or not isinstance(cases, dict)
        or not cases
        or len(cases) > 10000
        or not all(
            isinstance(key, str) and isinstance(value, str) and 0 < len(value) <= 128
            for key, value in cases.items()
        )
    ):
        raise ExperienceError("Invalid explicit evaluation groups")
    return cases
