"""Serial adaptive and multi-rung execution with durable decision replay."""

import time
from pathlib import Path

from chipcompiler.utility.workspace_lock import workspace_lock
from ecc_experience.dse.audit import audit_history, baseline_score
from ecc_experience.dse.multiobjective import measure_objectives, rank_trials
from ecc_experience.dse.optimizer import propose
from ecc_experience.dse.plan import invalid
from ecc_experience.dse.trial import check_source, execute_trial
from ecc_experience.dse.warm_start import freeze_warm_start
from ecc_experience.files import read_json
from ecc_experience.knowledge.release import verify_release
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.evidence import inspect_workspace
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner, cancellation_signals


def run_version2(plan: dict, limits, output, *, resume=False, select=None) -> dict:
    if not Path("/proc/self/task").is_dir():
        raise invalid("Controlled stage DSE requires Linux process-tree cancellation support")
    destination = Path(output).expanduser().absolute()
    if any(
        destination.resolve().is_relative_to(Path(plan[key]))
        or Path(plan[key]).is_relative_to(destination.resolve())
        for key in ("baseline_workspace", "store")
    ):
        raise invalid("DSE output overlaps source or store")
    if destination.is_symlink() or (destination.exists() and not resume):
        raise invalid("Use a new DSE output directory, or explicit --resume")
    if resume and not (destination / "result.json").is_file():
        raise invalid("DSE resume requires an existing result")
    check_source(plan)
    if freeze_warm_start(plan, plan["warm_start"]["limit"]) != plan["warm_start"]:
        raise invalid("Frozen warm-start provenance changed")
    if plan["release"]:
        release = verify_release(plan["release"], plan["store"])
        if release["status"] != "pass" or release["release_id"] != plan["release_id"]:
            raise invalid("Frozen warm-start release changed")
    destination.mkdir(parents=True, exist_ok=resume)
    try:
        with workspace_lock(destination / "result.json", blocking=False):
            return _run(plan, limits, destination, resume=resume, select=select)
    except BlockingIOError as exc:
        raise ExperienceError("DSE execution is busy", code="experience_workspace_busy") from exc


def _run(plan, limits, destination, *, resume, select):
    started = time.monotonic()
    result: dict
    if resume:
        result = read_json(destination / "result.json")
        audit_history(plan, result)
        if select and result.get("selection") and select != result["selection"]["candidate"]:
            raise invalid(
                "A validated selection cannot be changed within the same execution budget"
            )
        if result["status"] == "complete":
            return result
    else:
        result = {
            "schema": "ecc-experience-stage-dse-result/2",
            "plan_fingerprint": plan["plan_fingerprint"],
            "status": "running",
            "exit_code": 7,
            "trials": [],
            "promotions": [],
            "stage_winner": None,
            "full_validation": None,
            "fresh_validation": None,
            "elapsed_seconds": 0.0,
            "safe_to_apply": False,
            "generalization_status": "unproven",
            "selection": None,
        }
    elapsed = result["elapsed_seconds"]
    if resume and any(
        trial["status"] == "running"
        for trial in [
            *result["trials"],
            *[
                result[field]
                for field in ("full_validation", "fresh_validation")
                if result.get(field)
            ],
        ]
    ):
        elapsed = max(
            elapsed, limits.max_seconds - max(0, result["budget_expires_at"] - time.time())
        )
    result["budget_expires_at"] = time.time() + max(0, limits.max_seconds - elapsed)
    runner = CliRunner(
        destination, started + max(0, limits.max_seconds - elapsed), durable_receipts=True
    )
    runner.sequence = max(
        (
            int(path.stem.split("-")[1].split(".")[0])
            for path in destination.glob("command-*.request.json")
        ),
        default=0,
    )

    def save():
        result["elapsed_seconds"] = round(elapsed + time.monotonic() - started, 3)
        write_plan(destination / "result.json", result)

    result.update(status="running", exit_code=7)
    save()
    candidates = audit_history(plan, result)["candidates"]

    def screen(candidate, rung_index, decision=None):
        existing = next(
            (
                trial
                for trial in result["trials"]
                if trial["candidate_id"] == candidate["candidate_id"]
                and trial["rung"] == rung_index
            ),
            None,
        )
        if existing is not None and existing["status"] != "running":
            return existing
        record: dict = (
            existing if existing is not None else {"rung": rung_index, "decision": decision}
        )
        if existing is None:
            result["trials"].append(record)
        rung = plan["rungs"][rung_index]
        main = rung["objectives"][0]
        stage_plan = {
            **plan,
            "through_step": rung["through_step"],
            "objective": {key: main[key] for key in ("id", "unit", "scope", "corner")},
        }
        execute_trial(
            stage_plan,
            candidate,
            limits,
            runner,
            record,
            save,
            mode="screen",
            resume=existing is not None,
        )
        if record["status"] == "stage_passed":
            measured = measure_objectives(
                record["case_id"], plan["store"], rung["through_step"], rung["objectives"]
            )
            record.update(
                objective_values=measured["values"], objective_evidence=measured["evidence"]
            )
            if measured["status"] != "available":
                record.update(status="unknown", reason="multiobjective_evidence_unavailable")
        save()
        return record

    try:
        with cancellation_signals():
            if "baseline_evidence" not in result:
                result["baseline_evidence"] = inspect_workspace(
                    Path(plan["project"]), Path(plan["baseline_workspace"]), runner, runner.deadline
                )
                save()
            history = [trial for trial in result["trials"] if trial["rung"] == 0]
            if history and history[-1]["status"] == "running":
                pending = history.pop()
                proposed, decision = propose(plan, history)
                screen(proposed, 0, decision)
                history.append(pending)
            while (
                len(history) < plan["screening_trials"] and result.get("stop_reason") != "patience"
            ):
                proposed, decision = propose(plan, history)
                if proposed is None:
                    break
                candidates[proposed["candidate_id"]] = proposed
                record = screen(proposed, 0, decision)
                history.append(record)
                if record["status"] == "timeout":
                    result.update(status="timeout", exit_code=124)
                    return result
                stagnant = 0
                for offset, observed in enumerate(history):
                    prefix = history[: offset + 1]
                    ranked = rank_trials(prefix, plan["rungs"][0]["objectives"])
                    new_front = any(
                        point["id"] == observed["candidate_id"] and point["rank"] == 0
                        for point in ranked
                    )
                    unique_values = observed.get("objective_values") not in [
                        item.get("objective_values") for item in prefix[:-1]
                    ]
                    stagnant = 0 if new_front and unique_values else stagnant + 1
                if stagnant >= limits.patience:
                    result["stop_reason"] = "patience"
                    break
            for index, rung in enumerate(plan["rungs"][:-1]):
                trials = [trial for trial in result["trials"] if trial["rung"] == index]
                ranking = rank_trials(trials, rung["objectives"])
                promoted = [row["id"] for row in ranking[: rung["promote_count"]]]
                promotion = {
                    "from_rung": index,
                    "to_rung": index + 1,
                    "candidate_ids": promoted,
                    "ranking": ranking,
                }
                if index < len(result["promotions"]):
                    if result["promotions"][index] != promotion:
                        raise invalid("DSE promotion history changed")
                else:
                    result["promotions"].append(promotion)
                save()
                for identity in promoted:
                    record = screen(candidates[identity], index + 1)
                    if record["status"] == "timeout":
                        result.update(status="timeout", exit_code=124)
                        return result
            final_trials = [
                trial for trial in result["trials"] if trial["rung"] == len(plan["rungs"]) - 1
            ]
            ranking = rank_trials(final_trials, plan["objectives"])
            result["pareto_front"] = [row["id"] for row in ranking if row["rank"] == 0]
            if not ranking:
                result.update(
                    status="no_valid_stage_candidate",
                    exit_code=6
                    if any(
                        trial["status"] in {"failed", "blocked", "cancelled"}
                        for trial in result["trials"]
                    )
                    else 7,
                )
                return result
            chosen = select or (result.get("selection") or {}).get("candidate")
            if chosen is None and len(plan["objectives"]) == 1:
                chosen = ranking[0]["id"]
            if chosen is None:
                result.update(status="selection_required", exit_code=7)
                return result
            if chosen not in result["pareto_front"]:
                raise invalid("Selected candidate must belong to the final measured Pareto front")
            result["selection"] = {
                "candidate": chosen,
                "rule": "explicit"
                if select
                else (result.get("selection") or {}).get("rule", "single_objective"),
            }
            result["stage_winner"] = next(
                trial for trial in final_trials if trial["candidate_id"] == chosen
            )
            for field, mode in (("full_validation", "full"), ("fresh_validation", "fresh")):
                existing = result[field]
                if existing and existing["status"] == "passed":
                    continue
                if existing and existing["status"] != "running":
                    result.update(status=f"{field}_failed", exit_code=6)
                    return result
                record = existing if existing else {}
                result[field] = record
                execute_trial(
                    plan,
                    candidates[chosen],
                    limits,
                    runner,
                    record,
                    save,
                    mode=mode,
                    resume=existing is not None,
                )
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
            baseline, fresh = result["baseline_evidence"], result["fresh_validation"]
            score = baseline_score(plan, baseline)
            comparable = score is not None and fresh.get("qor_score") is not None
            delta = fresh["qor_score"] - score if comparable else None
            result.update(
                status="complete",
                exit_code=0,
                score_delta=delta,
                improved=delta > 0 if delta is not None else None,
                comparison_status="available" if comparable else "insufficient_evidence",
            )
            audit_history(plan, result)
            check_source(plan)
    except KeyboardInterrupt:
        result.update(status="cancelled", exit_code=130)
    except (ExperienceError, OSError) as exc:
        result.update(
            status="stopped",
            exit_code=21
            if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed"
            else 20
            if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy"
            else 1,
            reason=str(exc),
        )
    finally:
        save()
    return result
