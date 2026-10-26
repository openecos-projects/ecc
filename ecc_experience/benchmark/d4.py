"""Evaluate grid, adaptive, warm-start and model-assisted DSE evidence."""

from collections import Counter, defaultdict
from math import comb, isfinite
from pathlib import Path

from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

D4_SPEC_SCHEMA = "ecc-experience-d4-spec/1"
D4_REPORT_SCHEMA = "ecc-experience-d4-report/1"
STRATEGIES = ("grid", "adaptive", "adaptive_warm", "model_assisted")
MIN_DESIGNS = 6
MIN_FAMILIES = 3
MIN_SEEDS = 2


def evaluate_d4(spec: str | Path, output: str | Path) -> dict:
    spec_path = Path(spec).expanduser().absolute()
    payload = read_json(spec_path, 16 * 1024 * 1024)
    entries = _entries(payload)
    runs = [_load_run(spec_path.parent, entry) for entry in entries]
    designs = defaultdict(list)
    for run in runs:
        designs[run["design"]].append(run)

    reasons = []
    budget_signatures = {run["budget_signature"] for run in runs}
    if len(budget_signatures) != 1:
        reasons.append("equal_budget_not_established")
    families = {run["family"] for run in runs}
    seeds = {
        strategy: {run["seed"] for run in runs if run["strategy"] == strategy}
        for strategy in STRATEGIES
    }
    if any(len(seeds[strategy]) < MIN_SEEDS for strategy in STRATEGIES):
        reasons.append("insufficient_seeds")
    if any(seeds[strategy] != seeds["grid"] for strategy in STRATEGIES):
        reasons.append("seed_sets_not_matched")
    if len(families) < MIN_FAMILIES:
        reasons.append("insufficient_families")
    if len(designs) < MIN_DESIGNS:
        reasons.append("insufficient_independent_designs")
    if not _order_balanced(runs):
        reasons.append("run_order_not_balanced")

    for design, rows in designs.items():
        if {row["strategy"] for row in rows} != set(STRATEGIES):
            reasons.append(f"strategy_missing:{design}")
        if len({row["family"] for row in rows}) != 1:
            reasons.append(f"family_mismatch:{design}")
        if len({row["scope_signature"] for row in rows}) != 1:
            reasons.append(f"scope_mismatch:{design}")
        if any(not row["strategy_matches_plan"] for row in rows):
            reasons.append(f"strategy_provenance_mismatch:{design}")
        if any(row["result"]["status"] != "complete" for row in rows):
            reasons.append(f"run_not_complete:{design}")
        if any(
            row["strategy"] == "model_assisted"
            and row["result"].get("model", {}).get("status") != "available"
            for row in rows
        ):
            reasons.append(f"model_evidence_unavailable:{design}")

    metrics = [_metrics(row) for row in runs]
    strategy_summary = _strategy_summary(metrics)
    comparisons = [_compare(strategy, metrics, runs) for strategy in STRATEGIES[1:]]
    order_balanced = _order_balanced(runs)
    passed = not reasons
    result = {
        "schema": D4_REPORT_SCHEMA,
        "spec": str(spec_path),
        "spec_fingerprint": digest(payload),
        "status": "pass" if passed else "unknown",
        "exit_code": 0 if passed else 7,
        "reasons": sorted(set(reasons)),
        "summary": {
            "run_count": len(runs),
            "design_count": len(designs),
            "family_count": len(families),
            "seed_count": len({run["seed"] for run in runs}),
            "strategy_count": len({run["strategy"] for run in runs}),
            "minimum_designs": MIN_DESIGNS,
            "minimum_families": MIN_FAMILIES,
            "minimum_seeds": MIN_SEEDS,
            "equal_budget": len(budget_signatures) == 1,
            "order_balanced": order_balanced,
            "scope_consistent": not any(reason.startswith("scope_mismatch") for reason in reasons),
            "host_classes": sorted({run["host_class"] for run in runs if run["host_class"]}),
            "host_loads": [
                {
                    "design": run["design"],
                    "strategy": run["strategy"],
                    "seed": run["seed"],
                    "load": run["host_load"],
                }
                for run in runs
                if run["host_load"] is not None
            ],
        },
        "strategies": strategy_summary,
        "comparisons": comparisons,
        "runs": metrics,
        "generalization_status": "validated_for_declared_scope" if passed else "unproven",
        "promotion_allowed": passed
        and any(item["significant_positive_improvement"] for item in comparisons),
        "safe_to_apply": False,
        "limitations": [
            "D4 compares observed runs on the declared designs, families, seeds and budget",
            "Equal plan budgets do not guarantee equal host load or external interference",
            "A completed D4 report does not replace full and fresh validation for a "
            "selected design",
            "No recommendation is written to a workspace and no model is promoted automatically",
        ],
    }
    result["report_id"] = f"d4-{digest(result)}"
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("D4 report output must be a new file")
    write_plan(destination, result)
    return result


def _entries(payload: dict) -> list[dict]:
    if (
        payload.get("schema") != D4_SPEC_SCHEMA
        or set(payload) != {"schema", "runs"}
        or not isinstance(payload["runs"], list)
        or not payload["runs"]
        or len(payload["runs"]) > 10000
    ):
        raise invalid("Invalid D4 specification")
    allowed = {
        "design",
        "family",
        "strategy",
        "seed",
        "plan",
        "result",
        "order",
        "host_class",
        "host_load",
    }
    for entry in payload["runs"]:
        if (
            not isinstance(entry, dict)
            or not {"design", "family", "strategy", "seed", "plan", "result"} <= set(entry)
            or not set(entry) <= allowed
            or entry["strategy"] not in STRATEGIES
            or not all(
                isinstance(entry[key], str) and entry[key]
                for key in ("design", "family", "plan", "result")
            )
            or not isinstance(entry["seed"], (str, int))
            or isinstance(entry["seed"], bool)
        ):
            raise invalid("Invalid D4 run entry")
    return payload["runs"]


def _load_run(base: Path, entry: dict) -> dict:
    plan_path = _resolve(base, entry["plan"])
    result_path = _resolve(base, entry["result"])
    try:
        plan = read_json(plan_path, 64 * 1024 * 1024)
        result = read_json(result_path, 64 * 1024 * 1024)
    except (ExperienceError, OSError) as exc:
        raise invalid(f"Invalid D4 run evidence: {exc}") from exc
    if (
        plan.get("schema") != "ecc-experience-stage-dse-plan/2"
        or result.get("schema") != "ecc-experience-stage-dse-result/2"
        or result.get("plan_fingerprint") != plan.get("plan_fingerprint")
    ):
        raise invalid("D4 run plan and result are not a frozen version 2 pair")
    return {
        "design": entry["design"],
        "family": entry["family"],
        "strategy": entry["strategy"],
        "seed": entry["seed"],
        "order": entry.get("order"),
        "host_class": entry.get("host_class"),
        "host_load": entry.get("host_load"),
        "plan": plan,
        "result": result,
        "budget_signature": digest(
            {
                "limits": plan.get("limits"),
                "screening_trials": plan.get("screening_trials"),
                "execution": plan.get("execution"),
                "rungs": [
                    {
                        "through_step": rung.get("through_step"),
                        "promote_count": rung.get("promote_count"),
                    }
                    for rung in plan.get("rungs", [])
                ],
            }
        ),
        "scope_signature": digest(
            {
                "input_content_fingerprint": plan.get("input_content_fingerprint"),
                "process": plan.get("process"),
                "runtime": plan.get("runtime"),
                "objectives": plan.get("objectives"),
                "space": plan.get("space"),
            }
        ),
        "strategy_matches_plan": _strategy_matches(entry["strategy"], plan, result),
    }


def _strategy_matches(strategy: str, plan: dict, result: dict) -> bool:
    warm = plan.get("warm_start", {}).get("seeds", [])
    if strategy == "grid":
        return plan.get("strategy") == "grid"
    if strategy == "adaptive":
        return plan.get("strategy") == "adaptive" and not warm
    if strategy == "adaptive_warm":
        return plan.get("strategy") == "adaptive" and bool(warm)
    if strategy == "model_assisted":
        return result.get("model", {}).get("requested") is not None
    return False


def _metrics(run: dict) -> dict:
    plan = run["plan"]
    result = run["result"]
    trials = result.get("trials", [])
    statuses = Counter(trial.get("status", "unknown") for trial in trials)
    first = next(
        (
            index
            for index, trial in enumerate(trials)
            if trial.get("status") in {"stage_passed", "passed"}
        ),
        None,
    )
    elapsed = 0.0
    first_elapsed = None
    for index, trial in enumerate(trials):
        value = trial.get("elapsed_seconds", 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            elapsed += max(0.0, float(value))
        if index == first:
            first_elapsed = elapsed
    fresh = result.get("fresh_validation")
    final_qor = fresh.get("qor_score") if isinstance(fresh, dict) else None
    if not isinstance(final_qor, (int, float)) or isinstance(final_qor, bool):
        final_qor = None
    peak_rss = None
    for trial in trials:
        resources = trial.get("resources")
        if isinstance(resources, list):
            values = [
                item.get("observation", {}).get("peak_rss_bytes")
                for item in resources
                if isinstance(item, dict) and isinstance(item.get("observation"), dict)
            ]
            values = [
                value
                for value in values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if values:
                peak_rss = max(values)
    objective = plan.get("objectives", [{}])[0]
    return {
        "design": run["design"],
        "family": run["family"],
        "strategy": run["strategy"],
        "seed": run["seed"],
        "status": result.get("status"),
        "direction": objective.get("direction", "minimize"),
        "first_feasible_trial": first,
        "first_feasible_elapsed_seconds": first_elapsed,
        "recorded_trial_time_seconds": round(elapsed, 3),
        "wall_time_seconds": result.get("elapsed_seconds"),
        "executed_trials": len(trials),
        "failure_distribution": dict(sorted(statuses.items())),
        "final_qor": final_qor,
        "full_validation": _validation_status(result.get("full_validation")),
        "fresh_validation": _validation_status(fresh),
        "validation_signoff": {
            "full": _validation_signoff(result.get("full_validation")),
            "fresh": _validation_signoff(fresh),
        },
        "score_delta": result.get("score_delta"),
        "improved": result.get("improved"),
        "recommendation_hit": bool(
            result.get("selection")
            and isinstance(result.get("fresh_validation"), dict)
            and result["fresh_validation"].get("status") == "passed"
        ),
        "peak_rss_bytes": peak_rss,
        "budget_coverage": "available" if peak_rss is not None else "unknown",
        "model_metrics": _model_metrics(result),
    }


def _validation_status(value: object) -> str:
    return value.get("status", "unknown") if isinstance(value, dict) else "unknown"


def _validation_signoff(value: object) -> dict:
    if not isinstance(value, dict):
        return {"status": "unknown", "exit_code": None, "advisory_only": False}
    return {
        "status": value.get("signoff_status", "unknown"),
        "exit_code": value.get("signoff_exit_code"),
        "advisory_only": value.get("advisory_only", False),
    }


def _model_metrics(result: dict) -> dict:
    model = result.get("model")
    if not isinstance(model, dict) or model.get("status") != "available":
        return {
            "status": "unknown",
            "reason": model.get("reason") if isinstance(model, dict) else None,
        }
    metrics = {
        "status": "available",
        "release_id": model.get("release_id"),
        "model_id": model.get("model_id"),
        "policy": model.get("policy"),
        "used_for_selection": model.get("used_for_selection", False),
    }
    requested = model.get("requested")
    if isinstance(requested, str):
        try:
            from ecc_experience.modeling.predict import read_model_release

            validation = read_model_release(requested).get("validation", {})
            metrics["validation"] = {
                "status": validation.get("status", "unknown"),
                "metrics": validation.get("metrics"),
                "summary": validation.get("summary"),
            }
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            metrics["validation"] = {"status": "unknown", "reason": str(exc)}
    return metrics


def _strategy_summary(metrics: list[dict]) -> dict:
    result = {}
    for strategy in STRATEGIES:
        rows = [row for row in metrics if row["strategy"] == strategy]
        values = [row["final_qor"] for row in rows if row["final_qor"] is not None]
        result[strategy] = {
            "run_count": len(rows),
            "complete_count": sum(row["status"] == "complete" for row in rows),
            "mean_final_qor": sum(values) / len(values) if values else None,
            "mean_wall_time_seconds": _mean(
                [row["wall_time_seconds"] for row in rows if _number(row["wall_time_seconds"])]
            ),
            "mean_executed_trials": _mean([row["executed_trials"] for row in rows]),
            "failure_distribution": dict(
                sorted(
                    sum(
                        (Counter(row["failure_distribution"]) for row in rows),
                        Counter(),
                    ).items()
                )
            ),
            "model_metrics_available": sum(
                row["model_metrics"]["status"] == "available" for row in rows
            ),
            "recommendation_hit_count": sum(row["recommendation_hit"] for row in rows),
            "recommendation_hit_rate": (
                sum(row["recommendation_hit"] for row in rows) / len(rows) if rows else None
            ),
        }
    return result


def _compare(strategy: str, metrics: list[dict], runs: list[dict]) -> dict:
    baseline = {
        (row["design"], row["seed"]): row
        for row in metrics
        if row["strategy"] == "grid" and row["final_qor"] is not None
    }
    candidate = defaultdict(list)
    for row in metrics:
        if row["strategy"] == strategy and row["final_qor"] is not None:
            candidate[row["design"]].append(row)
    improvements = []
    for design, rows in sorted(candidate.items()):
        for row in rows:
            base = baseline.get((design, row["seed"]))
            if base is None:
                continue
            direction = row["direction"]
            delta = (
                row["final_qor"] - base["final_qor"]
                if direction == "maximize"
                else base["final_qor"] - row["final_qor"]
            )
            improvements.append(delta)
    wins = sum(value > 0 for value in improvements)
    losses = sum(value < 0 for value in improvements)
    ties = sum(value == 0 for value in improvements)
    p_value = _sign_test(wins, losses)
    mean = sum(improvements) / len(improvements) if improvements else None
    return {
        "strategy": strategy,
        "baseline": "grid",
        "paired_run_count": len(improvements),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "mean_improvement": mean,
        "sign_test_p_value": p_value,
        "status": "available" if improvements else "insufficient_evidence",
        "significant_positive_improvement": bool(
            improvements and mean is not None and mean > 0 and wins > losses and p_value <= 0.05
        ),
        "runs": [
            {
                "design": row["design"],
                "seed": row["seed"],
                "family": row["family"],
                "host_class": next(
                    run["host_class"]
                    for run in runs
                    if run["design"] == row["design"]
                    and run["strategy"] == row["strategy"]
                    and run["seed"] == row["seed"]
                ),
            }
            for row in metrics
            if row["strategy"] == strategy
        ],
    }


def _sign_test(wins: int, losses: int) -> float:
    totals = wins + losses
    if totals == 0:
        return 1.0
    return min(1.0, sum(comb(totals, value) for value in range(wins, totals + 1)) / 2**totals)


def _order_balanced(runs: list[dict]) -> bool:
    by_design = defaultdict(lambda: defaultdict(list))
    for run in runs:
        if not isinstance(run["order"], int):
            return False
        by_design[run["design"]][run["strategy"]].append(run["order"])
    for strategies in by_design.values():
        means = {strategy: sum(values) / len(values) for strategy, values in strategies.items()}
        if len(set(means.values())) != 1:
            return False
    return True


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.absolute() if path.is_absolute() else (base / path).absolute()


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_benchmark_invalid")
