"""Evaluate grid, adaptive, warm-start and model-assisted DSE evidence."""

from collections import Counter, defaultdict
from functools import lru_cache
from math import comb, isfinite
from pathlib import Path
from statistics import median

from ecc_experience.benchmark.separation import analyze_strategy_separation
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
            _validation_status(row["result"].get("full_validation")) != "passed" for row in rows
        ):
            reasons.append(f"full_validation_not_passed:{design}")
        if any(
            _validation_status(row["result"].get("fresh_validation")) != "passed" for row in rows
        ):
            reasons.append(f"fresh_validation_not_passed:{design}")
        if any(_final_qor(row["result"]) is None for row in rows):
            reasons.append(f"final_qor_unavailable:{design}")
        if any(
            row["strategy"] == "model_assisted"
            and not (
                row["result"].get("model", {}).get("status") == "available"
                and _available_model_predictions(row["result"]) > 0
            )
            for row in rows
        ):
            reasons.append(f"model_evidence_unavailable:{design}")
        warm_rows = [row for row in rows if row["strategy"] == "adaptive_warm"]
        if any(row["warm_start"]["status"] != "cross_design" for row in warm_rows):
            reasons.append(f"warm_start_not_cross_design:{design}")
        if any(row["warm_start"]["family_isolation"] != "explicit_groups" for row in warm_rows):
            reasons.append(f"warm_start_family_isolation_missing:{design}")
        if any(
            row["warm_start"]["status"] == "cross_design"
            and row["warm_start"]["cross_design_verified"] is not True
            for row in warm_rows
        ):
            reasons.append(f"warm_start_cross_design_unverified:{design}")
        if any(_declares_store(row) and row["resources"]["observation_count"] == 0 for row in rows):
            reasons.append(f"resource_evidence_unavailable:{design}")
        if any(_declares_store(row) and row["resources"]["load_1m"]["count"] == 0 for row in rows):
            reasons.append(f"host_load_evidence_unavailable:{design}")
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
    resource_acceptance = _resource_acceptance(metrics, runs)
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
            "resource_acceptance": resource_acceptance,
            "model_calibration": _model_calibration_summary(metrics),
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
            "Cross-design verification compares release design fingerprints and explicit "
            "evaluation groups; an unavailable release keeps the run unproven",
            "Resource acceptance requires declared runs to have step observations and host "
            "load; shared scope remains partial and is not treated as a hard memory bound",
            "No recommendation is written to a workspace and no model is promoted automatically",
            "Model calibration uses only the selected candidate and fresh QoR; it does not "
            "estimate candidate-level ranking accuracy",
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
    warm_start = _warm_start_evidence(plan, base)
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


def _warm_start_evidence(plan: dict, base: Path | None = None) -> dict:
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
    verification = _cross_design_verification(plan, warm, seeds, base or Path.cwd())
    return {
        "status": status,
        "experimental_cross_design": warm.get("experimental_cross_design") is True,
        "seed_count": len(seeds),
        "cross_design_seed_count": cross_design,
        "family_isolation": warm.get("family_isolation", "not_checked"),
        "release_id": plan.get("release_id"),
        **verification,
    }


def _cross_design_verification(plan: dict, warm: dict, seeds: list, base: Path) -> dict:
    result = {
        "cross_design_verified": None,
        "cross_design_verification": "not_applicable",
        "baseline_design_fingerprint": None,
        "seed_design_fingerprints": [],
        "evaluation_group_isolated": None,
    }
    if not seeds:
        return result
    release_path = warm.get("release")
    if not isinstance(release_path, str) or not release_path:
        result["cross_design_verification"] = "release_not_declared"
        return result
    release = _read_release(_resolve(base, release_path))
    if release["status"] != "available":
        result["cross_design_verification"] = release["reason"]
        return result
    cases = release["cases"]
    release_id = release["release_id"]
    if not release_id or (plan.get("release_id") and release_id != plan["release_id"]):
        result["cross_design_verification"] = "release_id_mismatch"
        result["cross_design_verified"] = False
        return result
    baseline_case_id = plan.get("baseline_case_id")
    baseline = cases.get(baseline_case_id)
    if not isinstance(baseline, dict):
        result["cross_design_verification"] = "baseline_case_absent_from_release"
        return result
    baseline_design = baseline.get("design_fingerprint")
    result["baseline_design_fingerprint"] = baseline_design
    if not isinstance(baseline_design, str) or not baseline_design:
        result["cross_design_verification"] = "baseline_design_fingerprint_unavailable"
        return result
    if (
        plan.get("input_content_fingerprint")
        and baseline.get("input_content_fingerprint") != plan["input_content_fingerprint"]
    ):
        result["cross_design_verification"] = "baseline_input_mismatch"
        result["cross_design_verified"] = False
        return result
    process = plan.get("process")
    process_fingerprint = process.get("fingerprint") if isinstance(process, dict) else None
    seed_designs = []
    for seed in seeds:
        if not isinstance(seed, dict) or not isinstance(seed.get("case_id"), str):
            result["cross_design_verification"] = "seed_case_unknown"
            return result
        case_id = seed["case_id"]
        observed = cases.get(case_id)
        if not isinstance(observed, dict):
            result["cross_design_verification"] = "seed_case_absent_from_release"
            return result
        design_fingerprint = observed.get("design_fingerprint")
        if not isinstance(design_fingerprint, str) or not design_fingerprint:
            result["cross_design_verification"] = "seed_design_fingerprint_unavailable"
            return result
        if design_fingerprint == baseline_design:
            result["cross_design_verification"] = "same_design_fingerprint"
            result["cross_design_verified"] = False
            return result
        if process_fingerprint and observed.get("process_fingerprint") != process_fingerprint:
            result["cross_design_verification"] = "seed_process_mismatch"
            result["cross_design_verified"] = False
            return result
        seed_designs.append(design_fingerprint)
    result["seed_design_fingerprints"] = seed_designs
    if warm.get("family_isolation") != "explicit_groups":
        result["cross_design_verification"] = "family_groups_not_declared"
        return result
    groups_path = warm.get("groups")
    if not isinstance(groups_path, str) or not groups_path:
        result["cross_design_verification"] = "family_groups_not_declared"
        return result
    groups = _read_groups(_resolve(base, groups_path))
    if groups["status"] != "available":
        result["cross_design_verification"] = groups["reason"]
        return result
    baseline_group = groups["cases"].get(baseline_case_id)
    if baseline_group is None:
        result["cross_design_verification"] = "baseline_group_unknown"
        return result
    for seed in seeds:
        seed_group = groups["cases"].get(seed["case_id"])
        if seed_group is None:
            result["cross_design_verification"] = "seed_group_unknown"
            return result
        if seed_group == baseline_group:
            result["cross_design_verification"] = "same_evaluation_group"
            result["evaluation_group_isolated"] = False
            result["cross_design_verified"] = False
            return result
    result["evaluation_group_isolated"] = True
    result["cross_design_verified"] = True
    result["cross_design_verification"] = "release_design_and_group_isolation"
    return result


@lru_cache(maxsize=32)
def _read_release(path: Path) -> dict:
    try:
        payload = read_json(path, 64 * 1024 * 1024)
    except (ExperienceError, OSError) as exc:
        return {"status": "unknown", "reason": f"release_unreadable:{exc}"}
    cases = payload.get("cases")
    if (
        payload.get("schema") != "ecc-experience-release/1"
        or not isinstance(payload.get("release_id"), str)
        or not payload["release_id"]
        or not isinstance(cases, list)
    ):
        return {"status": "unknown", "reason": "release_invalid"}
    indexed = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            return {"status": "unknown", "reason": "release_invalid"}
        if case["case_id"] in indexed:
            return {"status": "unknown", "reason": "release_duplicate_case"}
        indexed[case["case_id"]] = case
    return {
        "status": "available",
        "release_id": payload["release_id"],
        "cases": indexed,
    }


@lru_cache(maxsize=32)
def _read_groups(path: Path) -> dict:
    try:
        payload = read_json(path, 1024 * 1024)
    except (ExperienceError, OSError) as exc:
        return {"status": "unknown", "reason": f"family_groups_unreadable:{exc}"}
    cases = payload.get("cases")
    if (
        payload.get("schema_version") != 1
        or not isinstance(cases, dict)
        or not cases
        or not all(
            isinstance(key, str) and isinstance(value, str) and 0 < len(value) <= 128
            for key, value in cases.items()
        )
    ):
        return {"status": "unknown", "reason": "family_groups_invalid"}
    return {"status": "available", "cases": cases}


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


def _resource_acceptance(metrics: list[dict], runs: list[dict]) -> dict:
    declared = {
        (run["design"], run["strategy"], run["seed"]) for run in runs if _declares_store(run)
    }
    rows = [row for row in metrics if (row["design"], row["strategy"], row["seed"]) in declared]
    with_observations = [row for row in rows if row["resources"]["observation_count"] > 0]
    with_host_load = [
        row
        for row in with_observations
        if isinstance(row["observed_load_average"], list) and row["observed_load_average"]
    ]
    if not declared:
        status = "not_declared"
    elif len(with_host_load) == len(rows):
        status = "complete"
    elif with_observations:
        status = "partial"
    else:
        status = "unknown"
    return {
        "status": status,
        "declared_run_count": len(declared),
        "runs_with_observations": len(with_observations),
        "runs_with_host_load": len(with_host_load),
        "run_ratio": len(with_observations) / len(rows) if rows else 0.0,
        "host_load_ratio": len(with_host_load) / len(rows) if rows else 0.0,
        "measurement_scope": "step_observations_remain_partial_when_shared_process_tree",
        "limitation": (
            "Coverage complete does not make shared process-tree RSS a hard memory bound"
        ),
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
    return analyze_strategy_separation(metrics, STRATEGIES)


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
    declared_counts = set()
    budget_limits = set()
    required_budgets = set()
    budget_limited_runs = []
    missing_budget_runs = []
    for run in runs:
        space = run["plan"].get("space")
        combination_count = _space_combination_count(space)
        if combination_count is None:
            missing_budget_runs.append(_run_identity(run))
        else:
            declared_counts.add(combination_count)
            limits = run["plan"].get("limits")
            max_trials = limits.get("max_trials") if isinstance(limits, dict) else None
            if isinstance(max_trials, int) and not isinstance(max_trials, bool):
                budget_limits.add(max_trials)
                required = required_trial_budget(run["plan"], combination_count)
                required_budgets.add(required)
                if max_trials < required:
                    budget_limited_runs.append(_run_identity(run))
            else:
                missing_budget_runs.append(_run_identity(run))
        parameters = _selected_parameters(run["result"])
        if not isinstance(parameters, dict):
            continue
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
        "cartesian_coverage": {
            "status": "budget_limited"
            if budget_limited_runs
            else "unknown"
            if missing_budget_runs or not declared_counts
            else "complete",
            "declared_combination_counts": sorted(declared_counts),
            "trial_budget_limits": sorted(budget_limits),
            "required_trial_budgets": sorted(required_budgets),
            "budget_limited_runs": sorted(budget_limited_runs),
            "missing_budget_runs": sorted(missing_budget_runs),
            "limitation": (
                "The Cartesian grid must fit max_trials after reserving rung promotions and "
                "two independent full/fresh validations; otherwise the grid cannot be treated "
                "as fully explored"
                if budget_limited_runs
                else None
            ),
        },
        "limitation": (
            "Boundary-limited selections mean the frozen range did not bracket the observed "
            "preference; the next round must widen or shift the axis and re-freeze every run"
        ),
    }


def required_trial_budget(plan_or_budget: dict, combination_count: int) -> int:
    """Return the trial count needed for a full grid, promotions and validations."""
    rungs = plan_or_budget.get("rungs")
    later_trials = 0
    if isinstance(rungs, list):
        for rung in rungs[:-1]:
            if not isinstance(rung, dict):
                continue
            promote_count = rung.get("promote_count")
            if isinstance(promote_count, int) and not isinstance(promote_count, bool):
                later_trials += promote_count
    screening = plan_or_budget.get("screening_trials")
    screening_trials = combination_count
    if isinstance(screening, int) and not isinstance(screening, bool):
        screening_trials = max(screening_trials, screening)
    return screening_trials + later_trials + 2


def _space_combination_count(space: object) -> int | None:
    if not isinstance(space, dict) or not space:
        return None
    count = 1
    for values in space.values():
        if not isinstance(values, list) or not values:
            return None
        count *= len(values)
    return count


def _run_identity(run: dict) -> str:
    return f"{run['design']}:{run['strategy']}:{run['seed']}"


def _validation_status(value: object) -> str:
    return value.get("status", "unknown") if isinstance(value, dict) else "unknown"


def _final_qor(result: dict) -> float | None:
    fresh = result.get("fresh_validation")
    value = fresh.get("qor_score") if isinstance(fresh, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def _declares_store(run: dict) -> bool:
    store = run["plan"].get("store")
    return isinstance(store, str) and bool(store)


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
    predictions = _model_predictions(result)
    available = sum(item.get("status") == "available" for item in predictions)
    post_selection = _post_selection_calibration(result)
    if not isinstance(model, dict) or model.get("status") != "available":
        return {
            "status": "unknown",
            "reason": model.get("reason") if isinstance(model, dict) else None,
            "prediction_count": available,
            "unknown_prediction_count": len(predictions) - available,
            "post_selection": post_selection,
        }
    metrics = {
        "status": "available",
        "release_id": model.get("release_id"),
        "model_id": model.get("model_id"),
        "policy": model.get("policy"),
        "used_for_selection": model.get("used_for_selection", False),
        "prediction_count": available,
        "unknown_prediction_count": len(predictions) - available,
        "post_selection": post_selection,
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


def _model_predictions(result: dict) -> list[dict]:
    trials = result.get("trials")
    if not isinstance(trials, list):
        return []
    return [
        trial["model_prediction"]
        for trial in trials
        if isinstance(trial, dict) and isinstance(trial.get("model_prediction"), dict)
    ]


def _available_model_predictions(result: dict) -> int:
    return sum(item.get("status") == "available" for item in _model_predictions(result))


def _post_selection_calibration(result: dict) -> dict:
    selection = result.get("selection")
    candidate_id = selection.get("candidate") if isinstance(selection, dict) else None
    if not isinstance(candidate_id, str) or not candidate_id:
        return {"status": "unknown", "reason": "selected_candidate_unavailable"}
    fresh = result.get("fresh_validation")
    observed = fresh.get("qor_score") if isinstance(fresh, dict) else None
    observed_qor = _finite_number(observed)
    if observed_qor is None:
        return {
            "status": "unknown",
            "reason": "fresh_qor_unavailable",
            "candidate_id": candidate_id,
        }
    trials = result.get("trials")
    selected = next(
        (
            trial
            for trial in reversed(trials if isinstance(trials, list) else [])
            if isinstance(trial, dict)
            and trial.get("candidate_id") == candidate_id
            and isinstance(trial.get("model_prediction"), dict)
            and trial["model_prediction"].get("status") == "available"
        ),
        None,
    )
    if selected is None:
        return {
            "status": "unknown",
            "reason": "selected_prediction_unavailable",
            "candidate_id": candidate_id,
        }
    raw = selected["model_prediction"].get("prediction")
    predicted = raw.get("prediction") if isinstance(raw, dict) else raw
    predicted_qor = _finite_number(predicted)
    if predicted_qor is None:
        predicted = selected.get("predicted_qor")
        predicted_qor = _finite_number(predicted)
    if predicted_qor is None:
        return {
            "status": "unknown",
            "reason": "selected_prediction_invalid",
            "candidate_id": candidate_id,
        }
    residual = observed_qor - predicted_qor
    basis = None
    if isinstance(raw, dict):
        interval = raw.get("interval")
        if isinstance(interval, dict) and isinstance(interval.get("basis"), str):
            basis = interval["basis"]
    row = {
        "status": "available",
        "candidate_id": candidate_id,
        "predicted_final_qor": predicted_qor,
        "observed_final_qor": observed_qor,
        "residual": residual,
        "absolute_residual": abs(residual),
        "interval_status": "unknown",
        "lower_bound": None,
        "upper_bound": None,
        "covered": None,
        "target_coverage": None,
        "basis": basis,
    }
    if isinstance(raw, dict):
        lower = raw.get("lower_bound")
        upper = raw.get("upper_bound")
        interval = raw.get("interval")
        lower_bound = _finite_number(lower)
        upper_bound = _finite_number(upper)
        if lower_bound is not None and upper_bound is not None and lower_bound <= upper_bound:
            row.update(
                interval_status="available",
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                covered=lower_bound <= observed_qor <= upper_bound,
            )
        if isinstance(interval, dict):
            target_coverage = _finite_number(interval.get("target_coverage"))
            if target_coverage is not None:
                row["target_coverage"] = target_coverage
    return row


def _model_calibration_summary(metrics: list[dict]) -> dict:
    rows = [
        row
        for row in metrics
        if row["model_metrics"].get("post_selection", {}).get("status") == "available"
    ]
    errors = [row["model_metrics"]["post_selection"]["absolute_residual"] for row in rows]
    designs = {row["design"] for row in rows}
    families = {row["family"] for row in rows}
    interval_rows = [
        row
        for row in rows
        if row["model_metrics"]["post_selection"]["interval_status"] == "available"
    ]
    interval_designs = {row["design"] for row in interval_rows}
    covered = sum(
        row["model_metrics"]["post_selection"]["covered"] is True for row in interval_rows
    )
    targets = {
        row["model_metrics"]["post_selection"]["target_coverage"]
        for row in interval_rows
        if row["model_metrics"]["post_selection"]["target_coverage"] is not None
    }
    return {
        "status": "available"
        if len(designs) >= 3
        else "insufficient_evidence"
        if rows
        else "unknown",
        "selection_conditioned": True,
        "pair_count": len(rows),
        "design_count": len(designs),
        "family_count": len(families),
        "mae": sum(errors) / len(errors) if errors else None,
        "rmse": (sum(error**2 for error in errors) / len(errors)) ** 0.5 if errors else None,
        "interval": {
            "status": "available" if len(interval_designs) >= 3 else "insufficient_evidence",
            "design_count": len(interval_designs),
            "observation_count": len(interval_rows),
            "covered_count": covered,
            "observed_coverage": covered / len(interval_rows) if interval_rows else None,
            "target_coverage": targets.pop() if len(targets) == 1 else None,
        },
        "limitations": [
            "Only the selected candidate is compared with fresh final QoR",
            "Repeated seeds do not count as independent designs",
            "Selection-conditioned coverage is not an unbiased candidate ranking estimate",
        ],
    }


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
            "model_prediction_count": sum(
                row["model_metrics"].get("prediction_count", 0) for row in rows
            ),
            "model_used_for_selection_count": sum(
                row["model_metrics"].get("used_for_selection") is True for row in rows
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
    return _finite_number(value) is not None


def _finite_number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.absolute() if path.is_absolute() else (base / path).absolute()


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_benchmark_invalid")
