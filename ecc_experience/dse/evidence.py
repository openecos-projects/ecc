from pathlib import Path

from ecc_experience.knowledge.features import case_features


def stage_acceptance(case_id: str, store: str | Path, plan: dict, *, exit_code: int) -> dict:
    report = case_features(case_id, store, through_step=plan["through_step"])
    result = {
        "validation_scope": "flow_prefix_only",
        "status": "unknown",
        "stage_value": None,
        "full_signoff": "not_evaluated",
        "feature_status": report["status"],
    }
    if (
        exit_code != 0
        or report["status"] == "fail"
        or any(item["state"] != "Success" for item in report["steps"])
    ):
        return {**result, "status": "failed", "reason": "stage_execution_or_integrity_failed"}
    from ecc_experience.knowledge.store import ExperienceStore

    case = ExperienceStore(store).read(case_id)
    statuses = _checklists(case.facts, [item["step"] for item in report["steps"]])
    if any(item.get("blocked") is True or item.get("status") == "blocked" for item in statuses):
        return {**result, "status": "blocked", "reason": "prefix_checklist_blocked"}
    if any(item.get("status") != "passed" for item in statuses):
        return {**result, "reason": "prefix_checklist_unknown"}
    matching = [
        item
        for item in report["steps"][-1]["metrics"]
        if all(item.get(key) == value for key, value in plan["objective"].items())
        and item["status"] == "available"
    ]
    if len(matching) != 1:
        return {**result, "reason": "stage_objective_unavailable_or_ambiguous"}
    return {
        **result,
        "status": "stage_passed",
        "stage_value": matching[0]["value"],
        "objective_evidence": matching[0],
    }


def _checklists(facts: dict, names: list[str]) -> list[dict]:
    statuses = [
        step.get("checklist_status") for step in facts["flow"]["steps"] if step["name"] in names
    ]
    return [status if isinstance(status, dict) else {} for status in statuses]
