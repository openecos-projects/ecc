"""Freeze compatible observed seeds without relaxing existing matching filters."""

from chipcompiler.data.parameter_schema import lookup_schema
from ecc_experience.dse.plan import invalid
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.optimization.policy import configuration_differences


def freeze_warm_start(plan: dict, limit: int) -> dict:
    frozen = plan["warm_start"]
    if plan["release"] is None:
        return {**frozen, "release": None, "limit": limit, "seeds": [], "status": "not_requested"}
    repository = ExperienceStore(plan["store"])
    baseline = repository.read(plan["baseline_case_id"])
    context = baseline.facts.get("experienceExecutionContext")
    if not isinstance(context, dict) or context.get("runtime") != plan["runtime"]:
        return {
            **frozen,
            "seeds": [],
            "status": "insufficient_evidence",
        }
    experimental = frozen.get("experimental_cross_design", False)
    matched = match_cases(
        plan["baseline_case_id"],
        plan["store"],
        release=plan["release"],
        through_step=plan["rungs"][0]["through_step"],
        limit=limit,
        experimental_cross_design=experimental,
        groups=frozen.get("groups"),
    )
    facts: dict = baseline.facts
    specification = facts.get("workspaceSpec")
    if not isinstance(specification, dict) or not isinstance(specification.get("parameters"), dict):
        raise invalid("Warm-start baseline configuration is unavailable")
    configured = specification["parameters"]
    if not isinstance(configured, dict):
        raise invalid("Warm-start baseline configuration is invalid")
    seeds, used = [], []
    for item in matched["matches"]:
        compatible_design = (
            item.get("match_quality") == "compatible_design"
            or item.get("same_input_content") is False
        )
        evidence_level = item.get("parameter_evidence_level", "unknown")
        if experimental and compatible_design and evidence_level != "applied":
            continue
        candidate = repository.read(item["case_id"])
        candidate_specification = candidate.facts.get("workspaceSpec")
        if not isinstance(candidate_specification, dict) or not isinstance(
            candidate_specification.get("parameters"), dict
        ):
            continue
        observed = candidate_specification.get("parameters")
        if not isinstance(observed, dict):
            continue
        if configuration_differences(
            configured,
            observed,
            baseline_root=baseline.source.workspace_root,
            candidate_root=candidate.source.workspace_root,
        ) - set(plan["space"]):
            continue
        parameters = {}
        for key, domain in plan["space"].items():
            schema = lookup_schema(key)
            if schema is None:
                raise invalid("Warm-start parameter is absent from the ECC catalog")
            value = observed.get(key, schema.default)
            if value not in domain:
                break
            parameters[key] = value
        if len(parameters) != len(plan["space"]) or parameters in used:
            continue
        used.append(parameters)
        confidence = item.get("confidence", "observed_only")
        coverage = item.get("feature_coverage", 0.0)
        provenance = {
            "release": plan["release"],
            "release_id": plan.get("release_id"),
            "case_id": item["case_id"],
            "distance": item["distance"],
            "feature_coverage": coverage,
            "confidence": confidence,
        }
        seeds.append(
            {
                "case_id": item["case_id"],
                "distance": item["distance"],
                "parameters": parameters,
                "compatibility": item["compatibility"],
                "confidence": confidence,
                "feature_coverage": coverage,
                "release": plan["release"],
                "release_id": plan.get("release_id"),
                "provenance": provenance,
            }
        )
    return {
        **frozen,
        "seeds": seeds,
        "status": "matches_available" if seeds else "insufficient_evidence",
    }
