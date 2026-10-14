from datetime import UTC, datetime
from pathlib import Path

from ecc_experience.files import digest, file_digest, read_json
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan
from ecc_experience.study.evidence import acceptance, pair_compatibility, result_cost
from ecc_experience.study.spec import check_output, invalid, load_spec, resolve


def evaluate_study(
    spec_path: str | Path, store: str | Path, output: str | Path | None = None
) -> dict:
    spec, root, fingerprint = load_spec(spec_path)
    repository = ExperienceStore(store)
    frozen = verify_release(resolve(root, spec.release), store)
    try:
        frozen_time = datetime.fromisoformat(read_json(resolve(root, spec.release))["created_at"])
        if frozen_time.utcoffset() is None:
            raise ValueError("Release freeze time must include its timezone")
    except (ValueError, TypeError) as exc:
        raise invalid("Invalid release freeze timestamp") from exc
    training = [repository.read(item["case_id"]) for item in frozen["cases"]]
    training_inputs = {case.input_content_fingerprint for case in training}
    training_groups = {
        spec.groups[case.case_id] for case in training if case.case_id in spec.groups
    }
    heldout_inputs, heldout_groups = set(), set()
    findings, pairs = [], []
    if frozen["status"] != "pass":
        findings.append({"status": "fail", "reason": "frozen_release_not_verified"})
    if any(case.case_id not in spec.groups for case in training):
        findings.append({"status": "unknown", "reason": "training_group_missing"})
    for pair in spec.pairs:
        row = {
            "pair_id": pair.pair_id,
            "baseline_case_id": pair.baseline_case_id,
            "candidate_case_id": pair.candidate_case_id,
            "status": "unknown",
            "score_delta": None,
            "cost_comparison": "unavailable",
        }
        pairs.append(row)
        try:
            baseline = repository.read(pair.baseline_case_id)
            candidate = repository.read(pair.candidate_case_id)
            groups = [spec.groups.get(case.case_id) for case in (baseline, candidate)]
            heldout_inputs.update(case.input_content_fingerprint for case in (baseline, candidate))
            heldout_groups.update(group for group in groups if group)
            reasons = pair_compatibility(baseline, candidate, repository.root)
            if any(
                datetime.fromisoformat(case.collected_at) <= frozen_time
                for case in (baseline, candidate)
            ):
                reasons.append("heldout_not_collected_after_release_freeze")
            if not all(groups):
                findings.append(
                    {
                        "status": "unknown",
                        "pair_id": pair.pair_id,
                        "reason": "heldout_group_missing",
                    }
                )
            elif groups[0] != groups[1]:
                reasons.append("paired_design_group_mismatch")
            if any(
                case.input_content_fingerprint in training_inputs for case in (baseline, candidate)
            ) or any(group in training_groups for group in groups if group):
                reasons.append("training_heldout_leakage")
            row["group"] = groups[0]
            row["input_content_fingerprint"] = baseline.input_content_fingerprint
            left = acceptance(baseline, repository.case_directory(baseline.case_id))
            right = acceptance(candidate, repository.case_directory(candidate.case_id))
            row.update(baseline=left, candidate=right, reasons=reasons)
            if reasons:
                row["status"] = (
                    "fail"
                    if any(
                        reason
                        in {
                            "training_heldout_leakage",
                            "paired_design_group_mismatch",
                            "distinct_execution_attempts_required",
                            "heldout_not_collected_after_release_freeze",
                        }
                        for reason in reasons
                    )
                    else "unknown"
                )
            elif left["status"] == right["status"] == "pass":
                row.update(status="pass", score_delta=right["qor_score"] - left["qor_score"])
            if "fail" in (left["status"], right["status"]):
                row["status"] = "fail"
            if pair.baseline_result and pair.candidate_result:
                costs = {
                    "baseline": result_cost(resolve(root, pair.baseline_result), baseline),
                    "candidate": result_cost(resolve(root, pair.candidate_result), candidate),
                }
                row["costs"] = costs
                if (
                    all(item["status"] == "available" for item in costs.values())
                    and costs["baseline"]["budget"] == costs["candidate"]["budget"]
                ):
                    row.update(
                        cost_comparison="equal_recorded_budgets",
                        elapsed_delta_seconds=costs["candidate"]["elapsed_seconds"]
                        - costs["baseline"]["elapsed_seconds"],
                    )
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            row.update(status="unknown", reason=str(exc))
    if heldout_groups & training_groups or (heldout_inputs - {None}) & training_inputs:
        findings.append({"status": "fail", "reason": "training_heldout_leakage"})
    feedback = []
    for case_id in spec.feedback_case_ids:
        item = {"case_id": case_id, "status": "unknown"}
        feedback.append(item)
        try:
            case = repository.read(case_id)
            group = spec.groups.get(case_id)
            if (
                case.input_content_fingerprint in heldout_inputs
                or group in heldout_groups
                or case_id
                in {
                    key
                    for pair in spec.pairs
                    for key in (pair.baseline_case_id, pair.candidate_case_id)
                }
            ):
                item.update(status="fail", reason="heldout_feedback_leakage")
            elif not group:
                item["reason"] = "feedback_group_missing"
            else:
                item.update(acceptance(case, repository.case_directory(case_id)), group=group)
        except (ExperienceError, OSError) as exc:
            item["reason"] = str(exc)
    statuses = {item["status"] for item in [*findings, *pairs, *feedback]}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    per_design = {}
    for row in pairs:
        if row["status"] == "pass":
            per_design.setdefault(row["input_content_fingerprint"], []).append(row["score_delta"])
    design_deltas = [sum(values) / len(values) for values in per_design.values()]
    per_group = {}
    for group in heldout_groups:
        inputs = {
            row.get("input_content_fingerprint") for row in pairs if row.get("group") == group
        }
        deltas = [
            sum(per_design[key]) / len(per_design[key]) for key in inputs if key in per_design
        ]
        per_group[group] = {
            "input_count": len(inputs - {None}),
            "comparable_design_count": len(deltas),
            "mean_score_delta_per_design": sum(deltas) / len(deltas) if deltas else None,
        }
    result = {
        "schema": "ecc-experience-study-evaluation/1",
        "spec": str(Path(spec_path).expanduser().absolute()),
        "spec_fingerprint": fingerprint,
        "release_sha256": file_digest(resolve(root, spec.release))[0],
        "store": str(repository.root),
        "release_id": frozen["release_id"],
        "status": status,
        "exit_code": {"pass": 0, "fail": 6, "unknown": 7}[status],
        "pairs": pairs,
        "findings": findings,
        "feedback": feedback,
        "summary": {
            "pair_count": len(pairs),
            "passed_pairs": sum(row["status"] == "pass" for row in pairs),
            "training_group_count": len(training_groups),
            "heldout_group_count": len(heldout_groups),
            "independent_heldout_input_count": len(heldout_inputs - {None}),
            "comparable_design_count": len(per_design),
            "per_group": per_group,
            "mean_score_delta_per_design": sum(design_deltas) / len(design_deltas)
            if design_deltas
            else None,
            "controlled_budget_pairs": sum(
                row["cost_comparison"] == "equal_recorded_budgets" for row in pairs
            ),
        },
        "generalization_status": "unproven",
        "release_scope": "verified_observations_only",
        "limitations": [
            "Explicit family labels are user assertions, not inferred design taxonomy",
            "Repeated trials and input aliases do not add independent designs",
            "Missing experiment receipts cannot establish equal-budget search efficiency",
            "Single-design tests cannot prove generalization or calibrate resource prediction",
        ],
    }
    result["evaluation_fingerprint"] = digest(result)
    result["evaluated_at"] = datetime.now(UTC).isoformat()
    if output is not None:
        destination = Path(output).expanduser().absolute()
        case_ids = (
            {case.case_id for case in training}
            | set(spec.feedback_case_ids)
            | {
                case_id
                for pair in spec.pairs
                for case_id in (pair.baseline_case_id, pair.candidate_case_id)
            }
        )
        check_output(destination, repository, case_ids)
        write_plan(destination, result)
    return result
