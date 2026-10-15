"""Freeze compatible observed seeds without relaxing existing matching filters."""

from chipcompiler.data.parameter_schema import lookup_schema
from ecc_experience.dse.plan import invalid
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.optimization.policy import configuration_differences


def freeze_warm_start(plan: dict, limit: int) -> dict:
    if plan["release"] is None:
        return {"release": None, "limit": limit, "seeds": [], "status": "not_requested"}
    matched = match_cases(
        plan["baseline_case_id"],
        plan["store"],
        release=plan["release"],
        through_step=plan["rungs"][0]["through_step"],
        limit=limit,
    )
    baseline = ExperienceStore(plan["store"]).read(plan["baseline_case_id"])
    facts: dict = baseline.facts
    specification = facts.get("workspaceSpec")
    if not isinstance(specification, dict) or not isinstance(specification.get("parameters"), dict):
        raise invalid("Warm-start baseline configuration is unavailable")
    configured = specification["parameters"]
    seeds, used = [], []
    for item in matched["matches"]:
        observed = item["parameters"]["values"]
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
