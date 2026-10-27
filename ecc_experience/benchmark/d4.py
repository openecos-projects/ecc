"""Evaluate grid, adaptive, warm-start and model-assisted DSE evidence."""

from collections import Counter, defaultdict
from math import comb, isfinite
from pathlib import Path
from statistics import median

from ecc_experience.dse.audit import audit_history
from ecc_experience.dse.config_surface import describe_config_surface
from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

D4_SPEC_SCHEMA = "ecc-experience-d4-spec/1"
D4_REPORT_SCHEMA = "ecc-experience-d4-report/1"
STRATEGIES = ("grid", "adaptive", "adaptive_warm", "model_assisted")
MIN_DESIGNS = 6
MIN_FAMILIES = 3
MIN_SEEDS = 2
BUDGET_LIMIT_KEYS = ("max_seconds", "max_trials")


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
        warm_rows = [row for row in rows if row["strategy"] == "adaptive_warm"]
        if any(row["warm_start"]["status"] != "cross_design" for row in warm_rows):
            reasons.append(f"warm_start_not_cross_design:{design}")
        if any(row["warm_start"]["family_isolation"] != "explicit_groups" for row in warm_rows):
            reasons.append(f"warm_start_family_isolation_missing:{design}")
        receipt_statuses = {
            status
            for row in rows
            for status in _config_receipt_statuses(row["result"].get("trials", []))
        }
        if "mismatch" in receipt_statuses:
            reasons.append(f"config_receipt_mismatch:{design}")
        if "unavailable" in receipt_statuses:
            reasons.append(f"config_receipt_unavailable:{design}")

    metrics = [_metrics(row) for row in runs]
    strategy_summary = _strategy_summary(metrics)
    comparisons = [_compare(strategy, metrics, runs) for strategy in STRATEGIES[1:]]
    order_balanced = _order_balanced(runs)
    passed = not reasons
    resource_coverage = _resource_summary(metrics)
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
                    "design": row["design"],
                    "strategy": row["strategy"],
                    "seed": row["seed"],
                    "load": row["host_load"],
                    "source": row["host_load_source"],
                    "load_average": row["observed_load_average"],
                    "max_load_1m": row["observed_max_load_1m"],
                }
                for row in metrics
                if row["host_load"] is not None
            ],
            "resource_coverage": resource_coverage,
            "config_file_counts": dict(
                sorted(Counter(file for row in metrics for file in row["config_files"]).items())
            ),
            "config_files_by_strategy": {
                strategy: sorted(
                    {
                        file
                        for row in metrics
                        if row["strategy"] == strategy
                        for file in row["config_files"]
                    }
                )
                for strategy in STRATEGIES
            },
            "config_receipt_statuses": dict(
                sorted(
                    sum(
                        (Counter(row["config_receipt_statuses"]) for row in metrics),
                        Counter(),
                    ).items()
                )
            ),
            "warm_start_modes": dict(
                sorted(Counter(row["warm_start"]["status"] for row in metrics).items())
            ),
            "strategy_separation": _strategy_separation(metrics),
            "search_space_coverage": _search_space_summary(runs),
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
            "Resource evidence is read from immutable trial cases; shared process-tree "
            "observations are partial and are not isolated per-step attribution",
            "peak_rss_bytes is the maximum sampled RSS across a trial's step observations, "
            "not a sum and not a hard memory bound",
            "A completed D4 report does not replace full and fresh validation for a "
            "selected design",
            "adaptive_warm must use cross-design seeds with explicit family isolation; "
            "same-input seeds are reported as same_input and do not qualify",
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
    resources = _resource_evidence(plan, result)
    warm_start = _warm_start_evidence(plan)
    surface = plan.get("config_surface") or describe_config_surface(plan.get("space", {}))
    return {
        "design": entry["design"],
        "family": entry["family"],
        "strategy": entry["strategy"],
        "seed": entry["seed"],
        "order": entry.get("order"),
        "host_class": entry.get("host_class"),
        "host_load": entry.get("host_load"),
        "observed_load_average": resources["load_average"]["median"],
        "observed_max_load_1m": resources["load_1m"]["max"],
        "host_load_source": "spec"
        if entry.get("host_load") is not None
        else "case_observation"
        if resources["load_1m"]["count"]
        else None,
        "resources": resources,
        "warm_start": warm_start,
        "config_surface": surface,
        "config_files": sorted(surface["files"]),
        "plan": plan,
        "result": result,
        "budget_signature": _budget_signature(plan),
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


def _budget_signature(plan: dict) -> str:
    # Patience is an algorithm stopping rule and trial timeout is a hang guard.
    # Neither changes the shared trial count or wall-clock envelope. Larger
    # designs may need a different safety limit while every strategy still gets
    # the same allocated budget, concurrency and rungs.
    limits = plan.get("limits")
    limits = (
        {key: limits[key] for key in BUDGET_LIMIT_KEYS if key in limits}
        if isinstance(limits, dict)
        else {}
    )
    return digest(
        {
            "limits": limits,
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
    )


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


def _warm_start_evidence(plan: dict) -> dict:
    warm = plan.get("warm_start")
    warm = warm if isinstance(warm, dict) else {}
    seeds = warm.get("seeds")
    seeds = seeds if isinstance(seeds, list) else []
    cross_design = sum(
        isinstance(seed, dict) and seed.get("confidence") == "experimental" for seed in seeds
    )
    status = (
        "not_requested"
        if not seeds
        else "cross_design"
        if cross_design == len(seeds)
        else "mixed"
        if cross_design
        else "same_input"
    )
    return {
        "status": status,
        "experimental_cross_design": warm.get("experimental_cross_design") is True,
        "seed_count": len(seeds),
        "cross_design_seed_count": cross_design,
        "family_isolation": warm.get("family_isolation", "not_checked"),
        "release_id": plan.get("release_id"),
    }


def _resource_evidence(plan: dict, result: dict) -> dict:
    if not isinstance(plan.get("store"), str) or not plan["store"]:
        return _summarize_resources(
            [],
            source="none",
            reason="D4 plan has no experience store; resource evidence is unavailable",
        )
    try:
        audited = audit_history(plan, result)
    except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
        return _summarize_resources(
            [], source="case_observation", reason=f"Resource audit failed: {exc}"
        )
    evidence = audited["evidence"]
    records = []
    for index, trial in enumerate(result.get("trials", [])):
        checked = evidence.get(str(index), {})
        records.append(_resource_record(trial, checked))
    for field in ("full_validation", "fresh_validation"):
        trial = result.get(field)
        if isinstance(trial, dict):
            records.append(_resource_record(trial, evidence.get(field, {})))
    return _summarize_resources(records, source="case_observation")


def _resource_record(trial: dict, checked: dict) -> dict:
    resources = checked.get("resources", [])
    observations = []
    for item in resources if isinstance(resources, list) else []:
        observation = item.get("observation") if isinstance(item, dict) else None
        if isinstance(observation, dict):
            observations.append({"step": item.get("step"), "observation": observation})
    return {
        "candidate_id": trial.get("candidate_id"),
        "mode": trial.get("mode"),
        "status": trial.get("status"),
        "case_id": checked.get("case_id") or trial.get("case_id"),
        "verification": checked.get("status", "unknown"),
        "observations": observations,
    }


def _summarize_resources(records: list[dict], *, source: str, reason: str | None = None) -> dict:
    observations = [
        item["observation"] for record in records for item in record.get("observations", [])
    ]
    peaks = [
        value
        for value in (observation.get("peak_rss_bytes") for observation in observations)
        if _number(value)
    ]
    loads = []
    for observation in observations:
        host = observation.get("host")
        load = host.get("load_average") if isinstance(host, dict) else None
        if isinstance(load, list) and len(load) >= 1 and all(_number(value) for value in load[:3]):
            loads.append([float(value) for value in load[:3]])
    scopes = Counter(
        str(
            observation.get("scope") or observation.get("measurement", {}).get("scope") or "unknown"
        )
        for observation in observations
        if isinstance(observation.get("measurement"), dict) or observation.get("scope")
    )
    measurement_statuses = Counter(
        str(observation.get("measurement", {}).get("status", observation.get("status", "unknown")))
        for observation in observations
    )
    outcomes = Counter(
        str(observation.get("outcome", {}).get("status", "unknown"))
        if isinstance(observation.get("outcome"), dict)
        else str(observation.get("outcome", "unknown"))
        for observation in observations
    )
    hosts = []
    seen_hosts = set()
    for observation in observations:
        host = observation.get("host")
        if not isinstance(host, dict):
            continue
        marker = digest(host)
        if marker in seen_hosts:
            continue
        seen_hosts.add(marker)
        hosts.append(host)
    host_ids = sorted(
        {
            observation["host_id"]
            for observation in observations
            if isinstance(observation.get("host_id"), str) and observation["host_id"]
        }
    )
    load_1m = _numeric_summary([load[0] for load in loads])
    load_average = {
        "min": [min(load[index] for load in loads) for index in range(3)] if loads else None,
        "median": [median(load[index] for load in loads) for index in range(3)] if loads else None,
        "max": [max(load[index] for load in loads) for index in range(3)] if loads else None,
        "count": len(loads),
    }
    with_rss = sum(_number(observation.get("peak_rss_bytes")) for observation in observations)
    with_load = sum(
        isinstance(observation.get("host"), dict)
        and isinstance(observation["host"].get("load_average"), list)
        for observation in observations
    )
    records_with_observations = sum(bool(record.get("observations")) for record in records)
    observation_count = len(observations)
    status = (
        "unknown"
        if not observations
        else "available"
        if all(value == "available" for value in measurement_statuses)
        and with_rss == observation_count
        and with_load == observation_count
        else "partial"
    )
    if reason is None and status == "partial":
        reason = "One or more step measurements are partial or shared"
    return {
        "status": status,
        "source": source,
        "reason": reason,
        "record_count": len(records),
        "records_with_observations": records_with_observations,
        "observation_count": observation_count,
        "sample_count": sum(
            observation.get("sample_count", 0)
            for observation in observations
            if type(observation.get("sample_count")) is int
        ),
        "peak_rss_bytes": max(peaks) if peaks else None,
        "peak_rss_scope": "max_of_step_observations",
        "load_1m": load_1m,
        "load_average": load_average,
        "hosts": hosts,
        "host_ids": host_ids,
        "scope_counts": dict(sorted(scopes.items())),
        "measurement_status_counts": dict(sorted(measurement_statuses.items())),
        "outcome_counts": dict(sorted(outcomes.items())),
        "coverage": {
            "record_ratio": records_with_observations / len(records) if records else 0.0,
            "rss_observation_ratio": with_rss / observation_count if observation_count else 0.0,
            "host_load_observation_ratio": with_load / observation_count
            if observation_count
            else 0.0,
        },
        "limitations": [
            "Peak RSS is sampled and may miss short peaks or double-count shared pages",
            "Shared process-tree observations cannot be attributed to one step",
        ],
    }


def _resource_summary(metrics: list[dict]) -> dict:
    runs = [row for row in metrics if row["resources"]["observation_count"]]
    statuses = {row["resources"]["status"] for row in metrics}
    status = (
        "available"
        if statuses == {"available"}
        else "partial"
        if any(row["resources"]["observation_count"] for row in metrics)
        else "unknown"
    )
    return {
        "status": status,
        "run_count": len(metrics),
        "runs_with_observations": len(runs),
        "run_ratio": len(runs) / len(metrics) if metrics else 0.0,
        "record_count": sum(row["resources"]["record_count"] for row in metrics),
        "records_with_observations": sum(
            row["resources"]["records_with_observations"] for row in metrics
        ),
        "observation_count": sum(row["resources"]["observation_count"] for row in metrics),
        "sample_count": sum(row["resources"]["sample_count"] for row in metrics),
        "peak_rss_bytes": _numeric_summary(
            [row["peak_rss_bytes"] for row in metrics if _number(row["peak_rss_bytes"])]
        ),
        "host_load_1m": _numeric_summary(
            [
                row["observed_load_average"][0]
                for row in metrics
                if isinstance(row["observed_load_average"], list) and row["observed_load_average"]
            ]
        ),
        "scope_counts": dict(
            sorted(
                sum(
                    (Counter(row["resources"]["scope_counts"]) for row in metrics),
                    Counter(),
                ).items()
            )
        ),
        "measurement_status_counts": dict(
            sorted(
                sum(
                    (Counter(row["resources"]["measurement_status_counts"]) for row in metrics),
                    Counter(),
                ).items()
            )
        ),
        "runs": [
            {
                "design": row["design"],
                "strategy": row["strategy"],
                "seed": row["seed"],
                "status": row["resources"]["status"],
                "budget_coverage": row["budget_coverage"],
                "observations": row["resources"]["observation_count"],
                "record_ratio": row["resources"]["coverage"]["record_ratio"],
                "peak_rss_bytes": row["peak_rss_bytes"],
                "host_load_1m": row["observed_load_average"][0]
                if isinstance(row["observed_load_average"], list)
                else None,
                "max_load_1m": row["observed_max_load_1m"],
                "scopes": row["resources"]["scope_counts"],
            }
            for row in metrics
        ],
    }


def _numeric_summary(values: list[float]) -> dict:
    ordered = sorted(float(value) for value in values)
    return {
        "min": ordered[0] if ordered else None,
        "p50": ordered[len(ordered) // 2] if ordered else None,
        "p90": ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.9))] if ordered else None,
        "max": ordered[-1] if ordered else None,
        "count": len(ordered),
    }


def _compact_resources(resources: dict) -> dict:
    return {
        key: resources[key]
        for key in (
            "status",
            "source",
            "reason",
            "record_count",
            "records_with_observations",
            "observation_count",
            "sample_count",
            "peak_rss_bytes",
            "peak_rss_scope",
            "scope_counts",
            "measurement_status_counts",
            "outcome_counts",
            "coverage",
            "limitations",
        )
    }


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
    resources = run["resources"]
    peak_rss = resources["peak_rss_bytes"]
    observed_load = resources["load_average"]["median"]
    objective = plan.get("objectives", [{}])[0]
    selection = result.get("selection")
    selected_candidate = selection.get("candidate") if isinstance(selection, dict) else None
    selected_parameters = _selected_parameters(result)
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
        "selected_candidate": selected_candidate,
        "selected_parameters": selected_parameters,
        "score_delta": result.get("score_delta"),
        "improved": result.get("improved"),
        "recommendation_hit": bool(
            result.get("selection")
            and isinstance(result.get("fresh_validation"), dict)
            and result["fresh_validation"].get("status") == "passed"
        ),
        "peak_rss_bytes": peak_rss,
        "budget_coverage": resources["status"],
        "host_load": run["host_load"]
        if run["host_load"] is not None
        else observed_load[0]
        if isinstance(observed_load, list)
        else None,
        "host_load_source": run["host_load_source"],
        "warm_start": run["warm_start"],
        "config_files": run["config_files"],
        "config_surface": run["config_surface"],
        "config_receipt_statuses": _config_receipt_statuses(trials),
        "resource_coverage": resources["coverage"],
        "resource_scope": resources["scope_counts"],
        "resources": _compact_resources(resources),
        "observed_load_average": observed_load,
        "observed_max_load_1m": resources["load_1m"]["max"],
        "model_metrics": _model_metrics(result),
    }


def _strategy_separation(metrics: list[dict]) -> dict:
    by_design = defaultdict(dict)
    for row in metrics:
        if row["status"] == "complete" and row["selected_parameters"] is not None:
            by_design[row["design"]][row["strategy"]] = digest(row["selected_parameters"])
    separated = []
    converged = []
    unknown = []
    for design, selections in sorted(by_design.items()):
        if set(selections) != set(STRATEGIES):
            unknown.append(design)
        elif len(set(selections.values())) > 1:
            separated.append(design)
        else:
            converged.append(design)
    status = "separated" if separated else "converged" if converged else "unknown"
    return {
        "status": status,
        "separated_designs": separated,
        "converged_designs": converged,
        "unknown_designs": unknown,
    }


def _selected_parameters(result: dict) -> object | None:
    selection = result.get("selection")
    selected_candidate = selection.get("candidate") if isinstance(selection, dict) else None
    raw_trials = result.get("trials")
    trials: list[object] = raw_trials if isinstance(raw_trials, list) else []
    return next(
        (
            trial.get("parameters")
            for trial in trials
            if isinstance(trial, dict) and trial.get("candidate_id") == selected_candidate
        ),
        None,
    )


def _search_space_summary(runs: list[dict]) -> dict:
    axes: dict[str, dict] = {}
    for run in runs:
        parameters = _selected_parameters(run["result"])
        if not isinstance(parameters, dict):
            continue
        space = run["plan"].get("space")
        if not isinstance(space, dict):
            continue
        for axis, values in space.items():
            if (
                not isinstance(values, list)
                or not values
                or not all(_number(value) for value in values)
                or axis not in parameters
                or not _number(parameters[axis])
            ):
                continue
            ordered = sorted(float(value) for value in values)
            entry = axes.setdefault(
                axis,
                {
                    "lower_bound": ordered[0],
                    "upper_bound": ordered[-1],
                    "selected_values": set(),
                    "lower_boundary_selections": 0,
                    "upper_boundary_selections": 0,
                    "interior_selections": 0,
                    "bounds": set(),
                },
            )
            entry["bounds"].add((ordered[0], ordered[-1]))
            selected = float(parameters[axis])
            entry["selected_values"].add(selected)
            if selected == entry["lower_bound"]:
                entry["lower_boundary_selections"] += 1
            elif selected == entry["upper_bound"]:
                entry["upper_boundary_selections"] += 1
            else:
                entry["interior_selections"] += 1

    for entry in axes.values():
        selected = entry["selected_values"]
        lower = entry["lower_boundary_selections"]
        upper = entry["upper_boundary_selections"]
        interior = entry["interior_selections"]
        if len(entry.pop("bounds")) > 1:
            entry["status"] = "inconsistent_bounds"
        elif selected == {entry["lower_bound"]}:
            entry["status"] = "lower_boundary"
        elif selected == {entry["upper_bound"]}:
            entry["status"] = "upper_boundary"
        elif lower or upper:
            if interior:
                entry["status"] = "boundary_mixed"
            else:
                entry["status"] = "boundary_only"
        else:
            entry["status"] = "interior"
        entry["selected_values"] = sorted(selected)

    boundary_axes = sorted(
        axis
        for axis, entry in axes.items()
        if entry["status"] in {"lower_boundary", "upper_boundary", "boundary_only"}
    )
    inconsistent_axes = sorted(
        axis for axis, entry in axes.items() if entry["status"] == "inconsistent_bounds"
    )
    return {
        "status": (
            "boundary_limited"
            if boundary_axes
            else "inconsistent"
            if inconsistent_axes
            else "interior"
            if axes
            else "unknown"
        ),
        "boundary_axes": boundary_axes,
        "inconsistent_axes": inconsistent_axes,
        "axes": dict(sorted(axes.items())),
        "limitation": (
            "Boundary-limited selections mean the frozen range did not bracket the observed "
            "preference; the next round must widen or shift the axis and re-freeze every run"
        ),
    }


def _validation_status(value: object) -> str:
    return value.get("status", "unknown") if isinstance(value, dict) else "unknown"


def _config_receipt_statuses(trials: list[dict]) -> dict:
    receipts = [
        trial["config_receipt"]
        for trial in trials
        if isinstance(trial, dict) and isinstance(trial.get("config_receipt"), dict)
    ]
    return dict(sorted(Counter(receipt.get("status", "unknown") for receipt in receipts).items()))


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
                "calibration": validation.get("calibration"),
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
