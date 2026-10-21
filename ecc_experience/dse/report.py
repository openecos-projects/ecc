"""Summarize actual DSE evidence and freeze verified feedback for later datasets."""

import os
import shutil
import tempfile
from pathlib import Path

from ecc_experience.dse.plan import invalid, read_dse_plan
from ecc_experience.files import digest, file_digest, read_json
from ecc_experience.knowledge.release import create_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.optimization.plan import write_plan


def report_dse(plan: str | Path, result: str | Path, output: str | Path) -> dict:
    frozen, _limits = read_dse_plan(plan)
    if frozen["schema"] == "ecc-experience-stage-dse-plan/2":
        from ecc_experience.dse.report2 import report_version2

        return report_version2(frozen, result, output)
    result_path = Path(result).expanduser().absolute()
    payload = read_json(result_path)
    if (
        payload.get("schema") != "ecc-experience-stage-dse-result/1"
        or payload.get("plan_fingerprint") != frozen["plan_fingerprint"]
        or payload.get("status")
        not in {
            "complete",
            "timeout",
            "cancelled",
            "stopped",
            "no_valid_stage_candidate",
            "full_validation_failed",
            "fresh_validation_failed",
        }
        or type(payload.get("exit_code")) is not int
        or not isinstance(payload.get("trials"), list)
    ):
        raise invalid("DSE report requires a terminal result bound to its plan")
    repository = ExperienceStore(frozen["store"])
    rows = []
    eligible = set()
    records = [
        *payload["trials"],
        *[payload[name] for name in ("full_validation", "fresh_validation") if payload.get(name)],
    ]
    predicted_by_candidate = {}
    for record in payload["trials"]:
        if not isinstance(record, dict):
            raise invalid("DSE trial must be an object")
        prediction = record.get("model_prediction", {}).get("prediction", {}).get("prediction")
        predicted_by_candidate[record.get("candidate_id")] = prediction
    for record in records:
        if not isinstance(record, dict):
            raise invalid("DSE trial must be an object")
        candidate = next(
            (
                item
                for item in frozen["candidates"]
                if item["candidate_id"] == record.get("candidate_id")
            ),
            None,
        )
        if candidate is None or record.get("parameters") != candidate["parameters"]:
            raise invalid("DSE trial parameters do not match the frozen candidate")
        case_id = record.get("case_id")
        row = {
            "candidate_id": record.get("candidate_id"),
            "mode": record.get("mode"),
            "workspace": record.get("workspace"),
            "run_id": record.get("run_id"),
            "parameters": record.get("parameters", {}),
            "status": record.get("status", "unknown"),
            "reason": record.get("reason"),
            "stage_value": record.get("stage_value"),
            "predicted_qor": predicted_by_candidate.get(record.get("candidate_id")),
            "measured_qor": record.get("qor_score"),
            "elapsed_seconds": record.get("elapsed_seconds"),
            "case_id": case_id,
            "verification": "unknown",
            "resources": [],
            "feedback_eligible": False,
        }
        if case_id:
            case = repository.read(case_id)
            context = case.facts.get("experienceExecutionContext")
            specification = case.facts.get("workspaceSpec")
            flow = case.facts.get("flow")
            qor = case.facts.get("qorSnapshotExtension")
            if not isinstance(context, dict) or not isinstance(specification, dict):
                raise invalid("DSE trial case context is invalid")
            if not isinstance(flow, dict) or not isinstance(qor, dict):
                raise invalid("DSE trial case results are invalid")
            parameters = specification.get("parameters")
            steps = flow.get("steps")
            if not isinstance(parameters, dict) or not isinstance(steps, list):
                raise invalid("DSE trial case parameters or steps are invalid")
            if (
                case.input_content_fingerprint != frozen["input_content_fingerprint"]
                or case.source.attempt_id != record.get("run_id")
                or case.process_fingerprint != frozen["process"].get("fingerprint")
                or context.get("runtime") != frozen["runtime"]
                or any(
                    parameters.get(key) != value for key, value in candidate["parameters"].items()
                )
            ):
                raise invalid("DSE trial case does not match its declared input or run")
            verification = verify_case(case, repository.case_directory(case_id))
            row["verification"] = verification.status
            row["resources"] = [
                {"step": step.get("name"), "observation": step["resource_observation"]}
                for step in steps
                if isinstance(step, dict) and step.get("resource_observation")
            ]
            if verification.integrity == "fail":
                raise invalid("DSE trial evidence is corrupt")
            measured = qor.get("score") if qor.get("status") == "available" else None
            if row["measured_qor"] is not None and row["measured_qor"] != measured:
                raise invalid("DSE result QoR does not match its immutable case")
            row["measured_qor"] = measured
            row["prediction_error"] = (
                measured - row["predicted_qor"]
                if measured is not None and row["predicted_qor"] is not None
                else None
            )
            if verification.status == "pass" and verification.integrity == "pass":
                eligible.add(case_id)
                row["feedback_eligible"] = True
        rows.append(row)
    summary = {
        "schema": "ecc-experience-dse-summary/1",
        "plan_fingerprint": frozen["plan_fingerprint"],
        "result_sha256": file_digest(result_path)[0],
        "status": payload["status"],
        "exit_code": payload.get("exit_code", 7),
        "model_release_id": payload.get("model_release_id"),
        "selection_policy": payload.get("selection_policy", "measured_stage_objective"),
        "baseline": payload.get("baseline_evidence", {}),
        "score_delta": payload.get("score_delta"),
        "improved": payload.get("improved"),
        "stop_reason": payload.get("stop_reason"),
        "not_run_candidates": payload.get("not_run_candidates", []),
        "trials": rows,
        "feedback_case_ids": sorted(eligible),
        "convergence": {
            "screened_candidates": len(payload["trials"]),
            "stage_passed_candidates": sum(row["status"] == "stage_passed" for row in rows),
            "full_passed": bool(
                payload.get("full_validation", {})
                and payload["full_validation"].get("status") == "passed"
            ),
            "fresh_passed": bool(
                payload.get("fresh_validation", {})
                and payload["fresh_validation"].get("status") == "passed"
            ),
            "elapsed_seconds": payload.get("elapsed_seconds"),
            "validation_seconds": sum(
                row["elapsed_seconds"] or 0 for row in rows if row["mode"] in {"full", "fresh"}
            ),
        },
        "safe_to_apply": False,
        "next_action": "Build a versioned dataset; preserve design/family split before retraining",
    }
    summary["summary_id"] = f"dse-summary-{digest(summary)}"
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("DSE report output must be a new directory")
    for protected in (repository.root, Path(frozen["baseline_workspace"])):
        if destination.resolve().is_relative_to(protected) or protected.is_relative_to(
            destination.resolve()
        ):
            raise invalid("DSE report output must not overlap its store or source workspace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dse-report-", dir=destination.parent))
    try:
        if eligible:
            create_release(sorted(eligible), repository.root, staging / "feedback-release.json")
        write_plan(staging / "summary.json", summary)
        (staging / "summary.md").write_text(render_summary(summary), encoding="utf-8")
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return summary


def render_summary(summary: dict) -> str:
    lines = [
        "# ECC DSE result summary",
        "",
        f"Status: {summary['status']}; exit: {summary['exit_code']}",
        f"Selection: {summary['selection_policy']}; model: {summary['model_release_id']}",
        f"Baseline: {summary['baseline']}",
        f"Measured QoR delta: {summary['score_delta']}; improved: {summary['improved']}",
        f"Stop reason: {summary['stop_reason']}",
        "",
        "| Candidate | Mode | Status | Stage | Predicted QoR | Measured QoR | Seconds | Verified |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["trials"]:
        values = [
            row[key]
            for key in (
                "candidate_id",
                "mode",
                "status",
                "stage_value",
                "predicted_qor",
                "measured_qor",
                "elapsed_seconds",
                "verification",
            )
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(
        [
            "",
            "Full parameters, resource observation scope and failure reasons are in summary.json.",
            f"Verified feedback cases: {len(summary['feedback_case_ids'])}.",
            "Predictions do not replace measured QoR or full/fresh signoff validation.",
            summary["next_action"],
            "",
        ]
    )
    return "\n".join(lines)
