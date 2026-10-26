"""Bounded adaptive and multi-rung execution with durable decision replay."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from ecc_experience.modeling.dse import check_model, predict_trial
from ecc_experience.modeling.predict import read_model_release
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.evidence import inspect_workspace
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner, cancellation_signals


def run_version2(
    plan: dict,
    limits,
    output,
    *,
    resume=False,
    select=None,
    model_release=None,
    max_concurrent=None,
) -> dict:
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
    plan_limit = plan.get("execution", {}).get("max_concurrent", 1)
    effective_concurrency = plan_limit if max_concurrent is None else max_concurrent
    if (
        type(effective_concurrency) is not int
        or not 1 <= effective_concurrency <= plan_limit
        or effective_concurrency > limits.max_trials
    ):
        raise invalid("DSE concurrency must be between one and the frozen plan limit")
    destination.mkdir(parents=True, exist_ok=resume)
    try:
        with workspace_lock(destination / "result.json", blocking=False):
            return _run(
                plan,
                limits,
                destination,
                resume=resume,
                select=select,
                model_release=model_release,
                max_concurrent=effective_concurrency,
            )
    except BlockingIOError as exc:
        raise ExperienceError("DSE execution is busy", code="experience_workspace_busy") from exc


def _run(plan, limits, destination, *, resume, select, model_release, max_concurrent):
    started = time.monotonic()
    result: dict
    if resume:
        result = read_json(destination / "result.json")
        if result.get("max_concurrent") != max_concurrent:
            raise invalid("DSE resume cannot change execution concurrency")
        if result.get("model", {}).get("requested") != (
            str(Path(model_release).expanduser().absolute()) if model_release else None
        ):
            raise invalid("DSE resume cannot change the model release")
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
            "stop_reason": None,
            "safe_to_apply": False,
            "generalization_status": "unproven",
            "selection": None,
            "max_concurrent": max_concurrent,
            "execution_batches": 0,
            "model": _model_request(model_release),
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

    result_lock = threading.RLock()
    store_lock = threading.Lock()
    source_lock = threading.Lock()
    derive_lock = threading.Lock()

    def save():
        with result_lock:
            result["elapsed_seconds"] = round(elapsed + time.monotonic() - started, 3)
            write_plan(destination / "result.json", result)

    result.update(status="running", exit_code=7)
    save()
    candidates = audit_history(plan, result)["candidates"]

    model_cache = {}

    def stage_plan(rung_index):
        rung = plan["rungs"][rung_index]
        main = rung["objectives"][0]
        return {
            **plan,
            "through_step": rung["through_step"],
            "objective": {key: main[key] for key in ("id", "unit", "scope", "corner")},
        }

    def model_for_rung(rung_index):
        if not model_release:
            return None
        if rung_index not in model_cache:
            with result_lock:
                if rung_index not in model_cache:
                    try:
                        model_cache[rung_index] = (
                            check_model(stage_plan(rung_index), model_release),
                            None,
                        )
                    except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
                        model_cache[rung_index] = (None, str(exc))
        return model_cache[rung_index]

    def attach_model(record, rung_index):
        if record.get("status") != "stage_passed" or not model_release:
            return
        release, reason = model_for_rung(rung_index)
        if release is None:
            with result_lock:
                if result["model"].get("status") != "available":
                    result["model"].update(status="unknown", reason=reason)
                record["model_prediction"] = {
                    "status": "unknown",
                    "reason": reason,
                    "fallback": "measured_objective",
                }
            return
        try:
            prediction = predict_trial(
                stage_plan(rung_index), record, model_release, release["release_id"]
            )
            with result_lock:
                record["model_prediction"] = {
                    "status": "available",
                    "model_release_id": prediction["model_release_id"],
                    "model_id": prediction["model_id"],
                    "prediction": prediction["prediction"],
                    "fallback": "measured_objective_tie_break_only",
                }
                record["predicted_qor"] = prediction["prediction"]["prediction"]
                result["model"]["status"] = "available"
                result["model"]["release_id"] = release["release_id"]
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            with result_lock:
                record["model_prediction"] = {
                    "status": "unknown",
                    "reason": str(exc),
                    "fallback": "measured_objective",
                }

    def screen(candidate, rung_index, decision=None, existing=None, *, concurrency=None):
        if existing is None:
            existing = next(
                (
                    trial
                    for trial in result["trials"]
                    if trial["candidate_id"] == candidate["candidate_id"]
                    and trial["rung"] == rung_index
                ),
                None,
            )
        if existing is not None and existing.get("status") not in {None, "running"}:
            return existing
        record: dict = (
            existing if existing is not None else {"rung": rung_index, "decision": decision}
        )
        if existing is None:
            with result_lock:
                result["trials"].append(record)
        stage = stage_plan(rung_index)
        resuming = (
            existing is not None
            and existing.get("status") == "running"
            and "workspace_id" in existing
        )
        execute_trial(
            stage,
            candidate,
            limits,
            runner,
            record,
            save,
            mode="screen",
            resume=resuming,
            store_lock=store_lock,
            source_lock=source_lock,
            derive_lock=derive_lock,
            concurrency=concurrency,
            state_lock=result_lock,
        )
        if record["status"] == "stage_passed":
            rung = plan["rungs"][rung_index]
            measured = measure_objectives(
                record["case_id"], plan["store"], rung["through_step"], rung["objectives"]
            )
            with result_lock:
                record.update(
                    objective_values=measured["values"],
                    objective_evidence=measured["evidence"],
                )
                if measured["status"] != "available":
                    record.update(
                        status="unknown",
                        reason="multiobjective_evidence_unavailable",
                    )
        attach_model(record, rung_index)
        save()
        return record

    def run_screen_batch(items):
        if not items:
            return
        result["execution_batches"] += 1
        save()
        concurrency = {"current_flows": len(items), "max_concurrent": max_concurrent}

        def execute(item):
            candidate, rung_index, decision, record = item
            return screen(
                candidate,
                rung_index,
                decision,
                existing=record,
                concurrency=concurrency,
            )

        if len(items) == 1:
            execute(items[0])
            return
        with ThreadPoolExecutor(max_workers=min(max_concurrent, len(items))) as executor:
            futures = [executor.submit(execute, item) for item in items]
            failure = None
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException as exc:
                    failure = failure or exc
            if failure is not None:
                raise failure

    try:
        with cancellation_signals():
            if "baseline_evidence" not in result:
                result["baseline_evidence"] = inspect_workspace(
                    Path(plan["project"]), Path(plan["baseline_workspace"]), runner, runner.deadline
                )
                save()
            rung_zero = [trial for trial in result["trials"] if trial["rung"] == 0]
            running = [trial for trial in rung_zero if trial["status"] == "running"]
            if running:
                run_screen_batch(
                    [
                        (candidates[trial["candidate_id"]], 0, trial.get("decision"), trial)
                        for trial in running
                    ]
                )
            history = [
                trial
                for trial in result["trials"]
                if trial["rung"] == 0 and trial["status"] != "running"
            ]
            if any(trial["status"] == "timeout" for trial in history):
                result.update(status="timeout", exit_code=124)
                return result
            while (
                len(history) < plan["screening_trials"] and result.get("stop_reason") != "patience"
            ):
                slots = min(max_concurrent, plan["screening_trials"] - len(history))
                reserved = [trial["parameters"] for trial in rung_zero if "parameters" in trial]
                items = []
                next_candidate = len(rung_zero) + 1
                for slot in range(slots):
                    if max_concurrent == 1:
                        proposed, decision = propose(plan, history)
                    else:
                        proposed, decision = propose(
                            plan,
                            history,
                            excluded=reserved,
                            candidate_index=next_candidate + slot,
                        )
                    if proposed is None:
                        break
                    candidates[proposed["candidate_id"]] = proposed
                    reserved.append(proposed["parameters"])
                    record = {"rung": 0, "decision": decision}
                    with result_lock:
                        result["trials"].append(record)
                        rung_zero.append(record)
                    items.append((proposed, 0, decision, record))
                if not items:
                    break
                run_screen_batch(items)
                history = [
                    trial
                    for trial in result["trials"]
                    if trial["rung"] == 0 and trial["status"] != "running"
                ]
                if any(item[3].get("status") == "timeout" for item in items):
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
                for start in range(0, len(promoted), max_concurrent):
                    items = []
                    for identity in promoted[start : start + max_concurrent]:
                        existing = next(
                            (
                                trial
                                for trial in result["trials"]
                                if trial["rung"] == index + 1 and trial["candidate_id"] == identity
                            ),
                            None,
                        )
                        if existing is not None and existing.get("status") != "running":
                            continue
                        record = existing or {"rung": index + 1, "decision": None}
                        if existing is None:
                            with result_lock:
                                result["trials"].append(record)
                        items.append((candidates[identity], index + 1, None, record))
                    run_screen_batch(items)
                    if any(item[3].get("status") == "timeout" for item in items):
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
                chosen, used_model = _single_objective_choice(ranking, final_trials)
                if used_model:
                    result["model"]["used_for_selection"] = True
                    result["selection_policy"] = "measured_objective_model_tie_break"
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
            result.setdefault("selection_policy", "measured_stage_objective")
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
                    source_lock=source_lock,
                    derive_lock=derive_lock,
                    concurrency={"current_flows": 1, "max_concurrent": 1},
                    state_lock=result_lock,
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


def _single_objective_choice(ranking: list[dict], trials: list[dict]) -> tuple[str, bool]:
    best = ranking[0]
    values = {
        trial["candidate_id"]: trial.get("objective_values")
        for trial in trials
        if trial.get("status") == "stage_passed"
    }
    tied = [row for row in ranking if values.get(row["id"]) == values.get(best["id"])]
    predicted = {
        trial["candidate_id"]: trial.get("predicted_qor")
        for trial in trials
        if isinstance(trial.get("predicted_qor"), (int, float))
        and not isinstance(trial.get("predicted_qor"), bool)
    }
    if len(tied) > 1 and any(row["id"] in predicted for row in tied):
        selected = max(
            tied,
            key=lambda row: (predicted.get(row["id"], float("-inf")), row["id"]),
        )
        return selected["id"], selected["id"] in predicted
    return best["id"], False


def _model_request(path) -> dict:
    if path is None:
        return {
            "requested": None,
            "status": "not_requested",
            "policy": "not_requested",
            "used_for_selection": False,
        }
    source = str(Path(path).expanduser().absolute())
    try:
        release = read_model_release(source)
    except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "requested": source,
            "status": "unknown",
            "reason": str(exc),
            "policy": "measured_objective_fallback",
            "used_for_selection": False,
        }
    return {
        "requested": source,
        "status": "loaded",
        "release_id": release["release_id"],
        "model_id": release["model_id"],
        "policy": "measured_objective_tie_break_only",
        "used_for_selection": False,
    }
