"""Freeze compatible observed seeds without relaxing existing matching filters."""

from chipcompiler.data.parameter_schema import lookup_schema
from ecc_experience.dse.plan import invalid
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.optimization.policy import configuration_differences


def freeze_warm_start(plan: dict, limit: int) -> dict:
    if plan["release"] is None:
        return {"release": None, "limit": limit, "seeds": [], "status": "not_requested"}
    repository = ExperienceStore(plan["store"])
    baseline = repository.read(plan["baseline_case_id"])
    context = baseline.facts.get("experienceExecutionContext")
    if not isinstance(context, dict) or context.get("runtime") != plan["runtime"]:
        return {
            "release": plan["release"],
            "limit": limit,
            "seeds": [],
            "status": "insufficient_evidence",
        }
    matched = match_cases(
        plan["baseline_case_id"],
        plan["store"],
        release=plan["release"],
        through_step=plan["rungs"][0]["through_step"],
        limit=limit,
    )
    facts: dict = baseline.facts
    specification = facts.get("workspaceSpec")
    if not isinstance(specification, dict) or not isinstance(specification.get("parameters"), dict):
        raise invalid("Warm-start baseline configuration is unavailable")
    configured_value = specification["parameters"]
    if not isinstance(configured_value, dict):
        raise invalid("Warm-start baseline configuration is unavailable")
    configured = configured_value
    seeds, used = [], []
    for item in matched["matches"]:
        candidate = repository.read(item["case_id"])
        candidate_specification = candidate.facts.get("workspaceSpec")
        if not isinstance(candidate_specification, dict) or not isinstance(
            candidate_specification.get("parameters"), dict
        ):
            continue
        observed_value = candidate_specification["parameters"]
        if not isinstance(observed_value, dict):
            continue
        observed = observed_value
        if configuration_differences(configured, observed) - set(plan["space"]):
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
        seeds.append(
            {
                "case_id": item["case_id"],
                "distance": item["distance"],
                "parameters": parameters,
                "compatibility": item["compatibility"],
            }
        )
    return {
        "release": plan["release"],
        "limit": limit,
        "seeds": seeds,
        "status": "matches_available" if seeds else "insufficient_evidence",
    }
