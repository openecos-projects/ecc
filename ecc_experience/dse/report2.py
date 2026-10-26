"""Export measured Pareto fronts, rung costs and independently verified feedback."""

import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from ecc_experience.dse.audit import audit_history
from ecc_experience.dse.config_surface import config_files, describe_config_surface
from ecc_experience.dse.multiobjective import rank_trials
from ecc_experience.dse.plan import invalid
from ecc_experience.files import file_digest, read_json
from ecc_experience.knowledge.release import create_release
from ecc_experience.optimization.plan import write_plan


def summarize_version2(plan: dict, payload: dict) -> dict:
    if payload.get("status") not in {
        "complete",
        "selection_required",
        "cancelled",
        "stopped",
        "timeout",
        "no_valid_stage_candidate",
        "full_validation_failed",
        "fresh_validation_failed",
    }:
        raise invalid("DSE reporting requires a terminal result")
    audited = audit_history(plan, payload)
    rows = []
    feedback = set()
    surface = plan.get("config_surface") or describe_config_surface(plan["space"])
    records = [(str(index), trial) for index, trial in enumerate(payload["trials"])]
    records.extend(
        (field, payload[field])
        for field in ("full_validation", "fresh_validation")
        if payload.get(field)
    )
    for key, trial in records:
        checked = audited["evidence"][key]
        eligible = (
            checked.get("feedback_eligible", False)
            and trial.get("mode") in {"full", "fresh"}
            and trial["status"] == "passed"
        )
        if eligible:
            feedback.add(trial["case_id"])
        rows.append(
            {
                "candidate_id": trial["candidate_id"],
                "rung": trial.get("rung"),
                "mode": trial["mode"],
                "status": trial["status"],
                "reason": trial.get("reason"),
                "parameters": trial["parameters"],
                "config_files": config_files(trial["parameters"]),
                "config_receipt": trial.get("config_receipt"),
                "workspace": trial["workspace"],
                "run_id": trial["run_id"],
                "case_id": trial.get("case_id"),
                "objective_values": trial.get("objective_values"),
                "qor_score": trial.get("qor_score"),
                "elapsed_seconds": trial.get("elapsed_seconds"),
                "decision": trial.get("decision"),
                "verification": checked["status"],
                "resources": checked["resources"],
                "feedback_eligible": eligible,
            }
        )
    last = len(plan["rungs"]) - 1
    final_trials = [trial for trial in payload["trials"] if trial["rung"] == last]
    ranking = rank_trials(final_trials, plan["objectives"])
    front = [
        next(row for row in rows if row["candidate_id"] == point["id"] and row["rung"] == last)
        for point in ranking
        if point["rank"] == 0
    ]
    return {
        "schema": "ecc-experience-dse-summary/2",
        "plan_fingerprint": plan["plan_fingerprint"],
        "status": payload["status"],
        "exit_code": payload["exit_code"],
        "strategy": plan["strategy"],
        "algorithm": plan["algorithm"],
        "screening_trials": plan["screening_trials"],
        "patience_resolution": plan.get(
            "patience_resolution",
            {
                "mode": "fixed",
                "requested": plan["limits"]["patience"],
                "resolved": plan["limits"]["patience"],
            },
        ),
        "objectives": plan["objectives"],
        "config_surface": surface,
        "config_files": sorted(surface["files"]),
        "config_file_counts": dict(
            sorted(Counter(file for row in rows for file in row["config_files"]).items())
        ),
        "config_receipt_statuses": dict(
            sorted(
                Counter(
                    (row["config_receipt"] or {}).get("status", "not_checked") for row in rows
                ).items()
            )
        ),
        "warm_start": plan["warm_start"],
        "promotions": payload["promotions"],
        "selection": payload["selection"],
        "pareto_front": front,
        "ranking": ranking,
        "trials": rows,
        "feedback_case_ids": sorted(feedback),
        "budget": {
            "limits": plan["limits"],
            "executed_trials": len(rows),
            "elapsed_seconds": payload["elapsed_seconds"],
            "by_status": dict(Counter(row["status"] for row in rows)),
            "resource_scope": "per_step_observations_not_summed_memory",
        },
        "baseline": payload.get("baseline_evidence"),
        "baseline_comparison": payload.get("baseline_comparison"),
        "comparison_status": payload.get("comparison_status"),
        "score_delta": payload.get("score_delta"),
        "improved": payload.get("improved"),
        "stop_reason": payload.get("stop_reason"),
        "safe_to_apply": False,
        "generalization_status": "unproven",
    }


def report_version2(plan: dict, result, output) -> dict:
    path = Path(result).expanduser().resolve()
    original_sha256 = file_digest(path)[0]
    payload = read_json(path)
    summary = summarize_version2(plan, payload)
    summary["result_sha256"] = original_sha256
    destination = Path(output).expanduser().absolute()
    if (
        destination.exists()
        or destination.is_symlink()
        or any(
            destination.resolve().is_relative_to(Path(plan[key]))
            or Path(plan[key]).is_relative_to(destination.resolve())
            for key in ("store", "baseline_workspace")
        )
    ):
        raise invalid("DSE report requires a new directory outside source and store")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dse-report-", dir=destination.parent))
    try:
        write_plan(staging / "summary.json", summary)
        write_plan(
            staging / "pareto.json",
            {
                "objectives": summary["objectives"],
                "front": summary["pareto_front"],
                "safe_to_apply": False,
            },
        )
        if summary["feedback_case_ids"]:
            create_release(
                summary["feedback_case_ids"], plan["store"], staging / "feedback-release.json"
            )
        lines = [
            "# ECC DSE result",
            "",
            f"Status: {summary['status']}; exit: {summary['exit_code']}",
            f"Strategy: {summary['strategy']}; selection: {summary['selection']}",
            f"Patience: {summary['patience_resolution']}",
            f"Measured QoR delta: {summary['score_delta']}; improved: {summary['improved']}",
            f"Baseline comparison: {_render_baseline_comparison(summary['baseline_comparison'])}",
            "",
            "| Candidate | Rung / mode | Status | Objectives | Seconds | Verified |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in summary["trials"]:
            values = [
                row["candidate_id"],
                f"{row['rung']} / {row['mode']}",
                row["status"],
                row["objective_values"],
                row["elapsed_seconds"],
                row["verification"],
            ]
            lines.append(
                "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"
            )
        lines.extend(
            [
                "",
                "Pareto points describe the final measured prefix. "
                "Full and independent fresh validation remain required.",
                "summary.json retains parameters, all failures, decisions, "
                "promotions and resource scope.",
                "Single-design results do not establish generalization or optimization benefit.",
                "",
            ]
        )
        (staging / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        if file_digest(path)[0] != summary["result_sha256"]:
            raise invalid("DSE result changed while reporting")
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return summary


def _render_baseline_comparison(compared: dict | None) -> str:
    if not isinstance(compared, dict):
        return "unavailable (legacy result has no baseline comparison record)"
    reasons = compared.get("reasons")
    reason = ", ".join(reasons) if isinstance(reasons, list) and reasons else "none"
    return f"{compared.get('status')} ({reason})"
