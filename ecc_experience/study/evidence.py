import math
from pathlib import Path

from ecc_experience.files import file_digest, read_json
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.matching import compatibility_reasons
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, ExperienceError


def _source_finding(finding) -> bool:
    # Store-integrity checks run before source checks. Once integrity passes, a
    # failing digest can only describe the live source that produced the case.
    return finding.check in {"source", "file_digest"}


def _acceptance_finding(finding) -> bool:
    # Identity findings are advisory for acceptance, matching verify_case.
    return not finding.check.startswith("identity_")


def acceptance(case: ExperienceCase, directory: Path, *, require_source_fresh: bool = True) -> dict:
    verification = verify_case(case, directory)
    if verification.status == "fail":
        counted = [item for item in verification.findings if _acceptance_finding(item)]
        source_only = verification.integrity == "pass" and all(
            finding.status != "fail" or _source_finding(finding) for finding in counted
        )
        if require_source_fresh or not source_only:
            return {
                "status": "fail",
                "verification": "fail",
                "qor_score": None,
                "reason": "Case verification failed",
            }
    verification_status = verification.status
    if not require_source_fresh:
        non_source = [
            item.status
            for item in verification.findings
            if _acceptance_finding(item) and not _source_finding(item)
        ]
        verification_status = (
            "fail" if "fail" in non_source else "unknown" if "unknown" in non_source else "pass"
        )
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
    advisory_only = False
    signoff_status = "unknown"
    if (
        verification_status == "fail"
        or any(step.get("state") in {"Error", "Failed"} for step in steps)
        or any(item.get("blocked") is True or item.get("state") == "fail" for item in checklist)
        or any(
            isinstance(step.get("checklist_status"), dict)
            and step["checklist_status"].get("blocked") is True
            for step in steps
        )
    ):
        status = "fail"
    elif _strict_pass(
        case,
        verification_status,
        steps,
        checklist,
        facts.get("signoffAssessment"),
        feasibility,
        qor,
    ):
        status = "pass"
        signoff_status = "pass"
    elif _advisory_only_pass(
        case,
        verification_status,
        steps,
        checklist,
        facts.get("signoffAssessment"),
        feasibility,
        qor,
    ):
        status = "pass"
        advisory_only = True
    return {
        "status": status,
        "verification": verification_status,
        "qor_score": score if type(score) in {float, int} and math.isfinite(score) else None,
        "scope": "current_ecc_full_flow_checklist_signoff_qor",
        "signoff_status": signoff_status if status == "pass" else "unknown",
        "advisory_only": advisory_only,
    }


def _strict_pass(case, verification, steps, checklist, signoff, feasibility, qor) -> bool:
    return bool(
        verification == "pass"
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
        and isinstance(signoff, dict)
        and signoff.get("status") == "ready"
        and _feasibility_passed(feasibility)
        and _qor_passed(qor)
    )


def _advisory_only_pass(case, verification, steps, checklist, signoff, feasibility, qor) -> bool:
    if not (
        verification == "pass"
        and case.source.attempt_id
        and steps
        and all(
            step.get("state") == "Success"
            and isinstance(step.get("checklist_status"), dict)
            and step["checklist_status"].get("status") in {"passed", "attention"}
            and step["checklist_status"].get("blocked") is not True
            and not step["checklist_status"].get("failed_items")
            for step in steps
        )
        and checklist
        and all(
            item.get("state") in {"pass", "warning", "attention"}
            and item.get("blocked") is not True
            for item in checklist
        )
        and isinstance(signoff, dict)
        and signoff.get("status") == "attention"
        and _feasibility_passed(feasibility)
        and _qor_passed(qor)
    ):
        return False
    risks = signoff.get("risks")
    if not isinstance(risks, list) or not risks:
        return False
    details = []
    for risk in risks:
        if not isinstance(risk, dict) or risk.get("severity") != "warning":
            return False
        items = risk.get("details")
        if not isinstance(items, list) or not items:
            return False
        details.extend(items)
    return bool(details) and all(
        isinstance(item, dict)
        and item.get("policy") == "warn"
        and item.get("blocked") is not True
        and item.get("state") in {"warning", "attention"}
        for item in details
    )


def _feasibility_passed(feasibility) -> bool:
    return bool(
        isinstance(feasibility, dict)
        and feasibility.get("status") == "PASS"
        and all(
            isinstance(gate, dict) and gate.get("state") == "passed"
            for gate in feasibility.get("gates", [])
        )
    )


def _qor_passed(qor) -> bool:
    score = qor.get("score")
    return bool(
        qor.get("status") == "available" and type(score) in {float, int} and math.isfinite(score)
    )


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
