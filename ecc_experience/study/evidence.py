import math
from pathlib import Path

from ecc_experience.files import file_digest, read_json
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.matching import compatibility_reasons
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, ExperienceError


def acceptance(case: ExperienceCase, directory: Path) -> dict:
    verification = verify_case(case, directory)
    if verification.status == "fail":
        return {
            "status": "fail",
            "verification": "fail",
            "qor_score": None,
            "reason": "Case verification failed",
        }
    facts: dict = case.facts
    if not all(
        isinstance(facts.get(key), dict)
        for key in ("flow", "checklist", "qorSnapshotExtension", "signoffAssessment")
    ):
        return {
            "status": "unknown",
            "verification": verification.status,
            "qor_score": None,
            "reason": "Malformed acceptance sections",
        }
    steps = facts["flow"].get("steps", [])
    checklist = facts["checklist"].get("items", [])
    if not all(
        isinstance(items, list) and all(isinstance(item, dict) for item in items)
        for items in (steps, checklist)
    ):
        return {
            "status": "unknown",
            "verification": verification.status,
            "qor_score": None,
            "reason": "Malformed flow or checklist",
        }
    qor = facts.get("qorSnapshotExtension", {})
    feasibility = qor.get("feasibility", {})
    score = qor.get("score")
    status = "unknown"
    if (
        verification.status == "fail"
        or any(step.get("state") in {"Error", "Failed"} for step in steps)
        or any(item.get("blocked") is True or item.get("state") == "fail" for item in checklist)
        or any(
            isinstance(step.get("checklist_status"), dict)
            and step["checklist_status"].get("blocked") is True
            for step in steps
        )
    ):
        status = "fail"
    elif (
        verification.status == "pass"
        and case.source.attempt_id
        and steps
        and all(
            step.get("state") == "Success"
            and isinstance(step.get("checklist_status"), dict)
            and step["checklist_status"].get("status") == "passed"
            for step in steps
        )
        and checklist
        and all(
            item.get("state") == "pass" and item.get("blocked") is not True for item in checklist
        )
        and facts.get("signoffAssessment", {}).get("status") == "ready"
        and isinstance(feasibility, dict)
        and feasibility.get("status") == "PASS"
        and qor.get("status") == "available"
        and type(score) in {float, int}
        and math.isfinite(score)
    ):
        status = "pass"
    return {
        "status": status,
        "verification": verification.status,
        "qor_score": score if type(score) in {float, int} and math.isfinite(score) else None,
        "scope": "current_ecc_full_flow_checklist_signoff_qor",
    }


def pair_compatibility(
    baseline: ExperienceCase, candidate: ExperienceCase, store: Path
) -> list[str]:
    first: dict = baseline.facts
    second: dict = candidate.facts
    reasons = []
    if not all(
        isinstance(facts.get(key), dict)
        for facts in (first, second)
        for key in ("workspaceSpec", "qorSnapshotExtension")
    ):
        return ["comparison_sections_unknown"]
    if not all(
        isinstance(facts["workspaceSpec"].get("parameters", {}), dict) for facts in (first, second)
    ):
        return ["analysis_configuration_unknown"]
    if (
        baseline.case_id == candidate.case_id
        or not baseline.source.attempt_id
        or not candidate.source.attempt_id
        or baseline.source.attempt_id == candidate.source.attempt_id
    ):
        reasons.append("distinct_execution_attempts_required")
    if (
        baseline.input_content_fingerprint is None
        or baseline.input_content_fingerprint != candidate.input_content_fingerprint
    ):
        reasons.append("input_content_mismatch_or_unknown")
    if (
        baseline.process_fingerprint is None
        or baseline.process_fingerprint != candidate.process_fingerprint
    ):
        reasons.append("selected_process_mismatch_or_unknown")
    for key in ("design", "pdk", "flow"):
        if first.get("workspaceSpec", {}).get(key) != second.get("workspaceSpec", {}).get(key):
            reasons.append(f"{key}_mismatch")
    for key in ("scoringEngine", "profile"):
        left, right = (
            first.get("qorSnapshotExtension", {}).get(key),
            second.get("qorSnapshotExtension", {}).get(key),
        )
        if left is None or left != right:
            reasons.append(f"qor_{key}_mismatch_or_unknown")
    for case in (baseline, candidate):
        context = case.facts.get("experienceExecutionContext")
        if (
            not isinstance(context, dict)
            or context.get("attempt_id") != case.source.attempt_id
            or not isinstance(context.get("runtime"), dict)
            or not context["runtime"]
        ):
            reasons.append("execution_context_unknown")
            return reasons
    if first["experienceExecutionContext"].get("runtime") != second[
        "experienceExecutionContext"
    ].get("runtime"):
        reasons.append("runtime_mismatch")

    def analysis(facts: dict):
        return {
            key: value
            for key, value in facts.get("workspaceSpec", {}).get("parameters", {}).items()
            if key.startswith(("sta.", "route.", "design.frequency"))
        }

    if analysis(first) != analysis(second):
        reasons.append("analysis_configuration_mismatch")
    left = case_features(baseline.case_id, store)
    right = case_features(candidate.case_id, store)

    def timed_stages(features: dict) -> dict:
        return {
            stage["step"]: stage
            for stage in features["steps"]
            if isinstance(stage.get("analysis_context"), dict)
            and isinstance(stage["analysis_context"].get("timing_constraints"), dict)
            and stage["analysis_context"]["timing_constraints"].get("sdc_sha256")
        }

    first_stages, second_stages = timed_stages(left), timed_stages(right)
    common = [name for name in first_stages if name in second_stages]
    if not common:
        reasons.append("timing_analysis_evidence_unknown")
    else:
        name = common[-1]
        reasons.extend(compatibility_reasons(left, right, first_stages[name], second_stages[name]))
    return reasons


def result_cost(path: Path, case: ExperienceCase) -> dict:
    try:
        return _result_cost(path, case)
    except (ExperienceError, OSError) as exc:
        return {"status": "unknown", "reference": str(path), "reason": str(exc)}


def _result_cost(path: Path, case: ExperienceCase) -> dict:
    checksum = file_digest(path)[0]
    payload = read_json(path, 4 * 1024 * 1024)
    if checksum != file_digest(path)[0]:
        return {"status": "unknown", "reason": "Experiment result changed during read"}
    fresh = payload.get("fresh_validation")
    limits = payload.get("limits")
    trials = payload.get("trials")
    elapsed = payload.get("elapsed_seconds")
    if (
        payload.get("schema")
        not in {"ecc-experience-stage-dse-result/1", "ecc-experience-optimization-result/1"}
        or payload.get("status") != "complete"
        or payload.get("exit_code") != 0
        or not isinstance(fresh, dict)
        or fresh.get("case_id") != case.case_id
        or fresh.get("run_id") != case.source.attempt_id
        or fresh.get("status") != "passed"
        or not isinstance(fresh.get("workspace"), str)
        or Path(fresh["workspace"]).resolve() != Path(case.source.workspace_root).resolve()
        or not isinstance(limits, dict)
        or not isinstance(trials, list)
        or not all(isinstance(item, dict) for item in trials)
        or not isinstance(elapsed, (float, int))
        or isinstance(elapsed, bool)
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        return {"status": "unknown", "reason": "Unbound or incomplete experiment result"}
    records = [*trials, fresh]
    if isinstance(payload.get("full_validation"), dict):
        records.append(payload["full_validation"])
    budget = {
        key: limits.get(key) for key in ("max_trials", "max_seconds", "trial_timeout_seconds")
    }
    maximum = budget["max_trials"]
    if (
        not isinstance(maximum, int)
        or not all(type(value) is int and value > 0 for value in budget.values())
        or len(records) > maximum
    ):
        return {"status": "unknown", "reason": "Invalid experiment trial budget"}
    run_ids = [item.get("run_id") for item in records]
    if not all(isinstance(value, str) for value in run_ids) or len(set(run_ids)) != len(run_ids):
        return {"status": "unknown", "reason": "Repeated or missing trial identity"}
    return {
        "status": "available",
        "reference": str(path),
        "sha256": checksum,
        "elapsed_seconds": elapsed,
        "budget": budget,
        "attempted_trials": len(records),
        "failed_or_unknown_trials": sum(
            item.get("status") not in {"passed", "stage_passed"} for item in records
        ),
        "scope": "entire_recorded_experiment_including_search_and_fresh",
    }
