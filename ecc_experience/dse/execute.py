import time
from pathlib import Path

from ecc_experience.dse.plan import invalid, read_dse_plan
from ecc_experience.dse.trial import check_source, execute_trial
from ecc_experience.knowledge.release import verify_release
from ecc_experience.modeling.dse import check_model, predict_trial
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.evidence import inspect_workspace
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner, cancellation_signals


def run_dse(
    plan_path: str | Path,
    output: str | Path,
    *,
    model_release: str | Path | None = None,
    max_concurrent: int | None = None,
    resume: bool = False,
    select: str | None = None,
) -> dict:
    plan, limits = read_dse_plan(plan_path)
    if plan["schema"] == "ecc-experience-stage-dse-plan/2":
        from ecc_experience.dse.execute2 import run_version2

        return run_version2(
            plan,
            limits,
            output,
            resume=resume,
            select=select,
            model_release=model_release,
            max_concurrent=max_concurrent,
        )
    if max_concurrent is not None:
        raise invalid("--max-concurrent requires a version 2 DSE plan")
    if resume or select:
        raise invalid("Resume and explicit Pareto selection require a version 2 plan")
    check_source(plan)
    model = check_model(plan, model_release) if model_release is not None else None
    if not Path("/proc/self/task").is_dir():
        raise invalid("Controlled stage DSE requires Linux process-tree cancellation support")
    if plan["release"]:
        frozen = verify_release(plan["release"], plan["store"])
        if frozen["status"] != "pass" or frozen["release_id"] != plan["release_id"]:
            raise invalid("Frozen knowledge release changed or failed verification")
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("DSE output must be a new directory")
    for protected in (Path(plan["baseline_workspace"]), Path(plan["store"])):
        if destination.resolve().is_relative_to(protected) or protected.is_relative_to(
            destination.resolve()
        ):
            raise invalid("DSE output must not overlap source workspace or store")
    destination.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    runner = CliRunner(destination, started + limits.max_seconds)
    result: dict = {
        "schema": "ecc-experience-stage-dse-result/1",
        "plan_fingerprint": plan["plan_fingerprint"],
        "release_id": plan["release_id"],
        "status": "running",
        "exit_code": 7,
        "through_step": plan["through_step"],
        "objective": plan["objective"],
        "direction": plan["direction"],
        "baseline_stage_value": plan["baseline_stage_value"],
        "limits": limits.model_dump(),
        "trials": [],
        "stage_winner": None,
        "full_validation": None,
        "fresh_validation": None,
        "validation_scope": "stage_screen_then_full_and_fresh",
        "stop_reason": None,
        "model_release_id": model["release_id"] if model else None,
        "selection_policy": "predicted_final_qor" if model else "measured_stage_objective",
        "safe_to_apply": False,
    }

    def save():
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_plan(destination / "result.json", result)

    save()
    if model:
        write_plan(destination / "model-release.json", model)
    best_candidate = None
    best_rank = None
    stagnant = 0
    try:
        with cancellation_signals():
            result["baseline_evidence"] = inspect_workspace(
                Path(plan["project"]), Path(plan["baseline_workspace"]), runner, runner.deadline
            )
            for candidate in plan["candidates"]:
                record = {}
                result["trials"].append(record)
                execute_trial(plan, candidate, limits, runner, record, save, mode="screen")
                if record["status"] == "timeout":
                    result.update(status="timeout", exit_code=124, stop_reason="time_budget")
                    break
                value = record.get("stage_value")
                predicted = None
                if model and model_release is not None and record["status"] == "stage_passed":
                    record["model_prediction"] = predict_trial(
                        plan, record, model_release, model["release_id"]
                    )
                    predicted = record["model_prediction"]["prediction"]["prediction"]
                rank = (
                    predicted
                    if model
                    else (
                        -value if value is not None and plan["direction"] == "minimize" else value
                    )
                )
                better = (
                    record["status"] == "stage_passed"
                    and rank is not None
                    and (best_rank is None or rank > best_rank)
                )
                if better:
                    best_candidate = candidate
                    best_rank = rank
                    result["stage_winner"] = record
                    result["stage_improved"] = (
                        value < plan["baseline_stage_value"]
                        if plan["direction"] == "minimize"
                        else value > plan["baseline_stage_value"]
                    )
                    stagnant = 0
                else:
                    stagnant += 1
                save()
                if stagnant >= limits.patience:
                    result["stop_reason"] = "patience"
                    break
            if result["exit_code"] == 124:
                return result
            if best_candidate is None:
                result.update(
                    status="no_valid_stage_candidate",
                    exit_code=7
                    if all(item["status"] == "unknown" for item in result["trials"])
                    else 6,
                )
                return result
            result["stop_reason"] = result["stop_reason"] or "candidates_exhausted"
            for field, mode in (("full_validation", "full"), ("fresh_validation", "fresh")):
                record = {}
                result[field] = record
                execute_trial(plan, best_candidate, limits, runner, record, save, mode=mode)
                if record["status"] != "passed":
                    result.update(
                        status=f"{field}_failed",
                        exit_code=124
                        if record["status"] == "timeout"
                        else 7
                        if record["status"] == "unknown"
                        else 6,
                    )
                    return result
            baseline = result["baseline_evidence"]
            fresh = result["fresh_validation"]
            comparable = (
                baseline["status"] == "passed"
                and baseline.get("qor_score") is not None
                and fresh.get("qor_score") is not None
            )
            delta = fresh["qor_score"] - baseline["qor_score"] if comparable else None
            result.update(
                status="complete",
                exit_code=0,
                score_delta=delta,
                improved=delta > 0 if delta is not None else None,
                comparison_status="available" if comparable else "insufficient_evidence",
            )
            check_source(plan)
    except KeyboardInterrupt:
        result.update(status="cancelled", exit_code=130, stop_reason="user_interrupt")
    except (ExperienceError, OSError) as exc:
        result.update(
            status="stopped",
            reason=str(exc),
            exit_code=21
            if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed"
            else 1,
        )
    finally:
        attempted = {item.get("candidate_id") for item in result["trials"]}
        result["not_run_candidates"] = [
            item["candidate_id"]
            for item in plan["candidates"]
            if item["candidate_id"] not in attempted
        ]
        save()
    return result
