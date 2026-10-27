"""Plan the next benchmark round from one frozen campaign manifest."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ecc_experience.benchmark.d4 import (
    MIN_DESIGNS,
    MIN_FAMILIES,
    MIN_SEEDS,
    STRATEGIES,
)
from ecc_experience.benchmark.separation import analyze_strategy_separation
from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.campaign import CAMPAIGN_MANIFEST_SCHEMA
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

NEXT_SCHEMA = "ecc-experience-benchmark-next/1"


def plan_next_benchmark(manifest_path: str | Path, output: str | Path) -> dict[str, Any]:
    source = Path(manifest_path).expanduser().absolute()
    manifest = read_json(source, 64 * 1024 * 1024)
    runs = _runs(manifest)
    designs = sorted({row["design"] for row in runs})
    families = sorted({row["family"] for row in runs})
    seeds = sorted({row["seed"] for row in runs}, key=str)

    missing_ids = _missing_run_ids(runs, designs, seeds)
    invalid_ids = _invalid_run_ids(runs)
    priorities = _design_priorities(runs, designs, seeds)
    search_actions = _search_actions(manifest.get("search", {}))
    coverage_actions = _coverage_actions(len(designs), len(families), len(seeds))
    model_actions = _model_actions(manifest.get("model_evidence", {}))
    exploration_ids = sorted(set(missing_ids) | set(invalid_ids))
    limits = _per_run_limits(runs)
    new_designs = max(
        0,
        MIN_DESIGNS - len(designs),
        MIN_FAMILIES - len(families),
    )
    seed_gap = max(0, MIN_SEEDS - len(seeds))
    confirmation_runs = (
        new_designs * len(STRATEGIES) * MIN_SEEDS
        + len(designs) * len(STRATEGIES) * seed_gap
    )
    actions = [*coverage_actions, *search_actions, *model_actions]
    action_required = bool(actions or exploration_ids) or any(
        row["priority"] in {"high", "medium"} for row in priorities
    )
    result = {
        "schema": NEXT_SCHEMA,
        "mode": "planning_only",
        "status": "action_required" if action_required else "ready_for_confirmation",
        "source_manifest": str(source),
        "source_manifest_sha256": digest(manifest),
        "campaign_id": manifest.get("campaign_id"),
        "current": {
            "runs": len(runs),
            "designs": len(designs),
            "families": len(families),
            "seeds": len(seeds),
            "design_names": designs,
            "family_names": families,
            "seed_values": seeds,
            "equal_budget": bool(manifest.get("budget", {}).get("equal_budget")),
        },
        "confirmation_gate": {
            "minimum_designs": MIN_DESIGNS,
            "minimum_families": MIN_FAMILIES,
            "minimum_seeds": MIN_SEEDS,
            "design_gap": max(0, MIN_DESIGNS - len(designs)),
            "family_gap": max(0, MIN_FAMILIES - len(families)),
            "seed_gap": seed_gap,
        },
        "priorities": priorities,
        "actions": actions,
        "budget": {
            "per_run_limits": limits,
            "exploration": {
                "run_count_floor": len(exploration_ids),
                "run_ids": exploration_ids,
                "reason": (
                    "Complete missing strategy/seed combinations and rerun invalid evidence "
                    "before widening the search space"
                ),
            },
            "confirmation": {
                "minimum_new_designs": new_designs,
                "minimum_new_families": max(0, MIN_FAMILIES - len(families)),
                "minimum_additional_seed_runs": len(designs) * len(STRATEGIES) * seed_gap,
                "minimum_runs": confirmation_runs,
                "reason": (
                    "Confirmation uses new independent designs/families and the same reviewed "
                    "four-strategy budget; it cannot reuse the exploration round as held-out"
                ),
            },
        },
        "policy": {
            "planning_only": True,
            "safe_to_apply": False,
            "training_allowed_in_same_round": False,
            "promotion_allowed": False,
            "requires_runtime_freeze": True,
            "requires_independent_designs": True,
        },
    }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise _invalid("Benchmark next-round output must be a new file")
    write_plan(destination, result)
    return result


def _runs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema") != CAMPAIGN_MANIFEST_SCHEMA:
        raise _invalid("Benchmark next-round planning requires a campaign manifest")
    raw_runs = manifest.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise _invalid("Campaign manifest has no runs")
    runs = []
    seen = set()
    for row in raw_runs:
        if not isinstance(row, dict):
            raise _invalid("Campaign manifest run must be an object")
        design = row.get("design")
        family = row.get("family")
        strategy = row.get("strategy")
        seed = row.get("seed")
        if (
            not isinstance(design, str)
            or not design
            or not isinstance(family, str)
            or not family
            or strategy not in STRATEGIES
            or isinstance(seed, bool)
            or not isinstance(seed, (int, str))
        ):
            raise _invalid("Campaign manifest has an invalid run identity")
        key = (design, strategy, seed)
        if key in seen:
            raise _invalid("Campaign manifest has duplicate run identities")
        seen.add(key)
        runs.append(row)
    return runs


def _missing_run_ids(
    runs: list[dict[str, Any]], designs: list[str], seeds: list[Any]
) -> list[str]:
    present = {_run_id(row) for row in runs}
    expected = {
        _run_id({"design": design, "strategy": strategy, "seed": seed})
        for design in designs
        for strategy in STRATEGIES
        for seed in seeds
    }
    return sorted(expected - present)


def _invalid_run_ids(runs: list[dict[str, Any]]) -> list[str]:
    return sorted(
        _run_id(row)
        for row in runs
        if row.get("status") != "complete"
        or row.get("full_validation") != "passed"
        or row.get("fresh_validation") != "passed"
    )


def _design_priorities(
    runs: list[dict[str, Any]], designs: list[str], seeds: list[Any]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        grouped[row["design"]].append(row)
    separation = analyze_strategy_separation(
        [
            row
            for row in runs
            if row.get("status") == "complete"
            and row.get("full_validation") == "passed"
            and row.get("fresh_validation") == "passed"
        ],
        STRATEGIES,
    )
    separation_by_design = {
        **{design: "separated" for design in separation["separated_designs"]},
        **{design: "converged" for design in separation["converged_designs"]},
        **{design: "unstable" for design in separation["unstable_designs"]},
    }
    priorities = []
    for design in designs:
        rows = grouped[design]
        present = {row["strategy"] for row in rows}
        missing = sorted(set(STRATEGIES) - present)
        invalid = sorted(
            _run_id(row)
            for row in rows
            if row.get("status") != "complete"
            or row.get("full_validation") != "passed"
            or row.get("fresh_validation") != "passed"
        )
        quality = Counter(_quality_level(row) for row in rows)
        quality_gaps = sorted(
            _run_id(row) for row in rows if _quality_level(row) != "high"
        )
        resource_gaps = sorted(
            _run_id(row)
            for row in rows
            if _check(row, "resource_available") is False
            or _check(row, "feature_usable") is False
        )
        model_rows = [row for row in rows if row["strategy"] == "model_assisted"]
        model_available = any(_model_status(row) == "available" for row in model_rows)
        separation_status = separation_by_design.get(design, "unknown")
        reasons = []
        if missing:
            reasons.append({"code": "strategy_missing", "strategies": missing})
        if invalid:
            reasons.append({"code": "run_invalid", "run_ids": invalid})
        if quality_gaps:
            reasons.append({"code": "quality_gap", "run_ids": quality_gaps})
        if resource_gaps:
            reasons.append({"code": "resource_evidence_incomplete", "run_ids": resource_gaps})
        if model_rows and not model_available:
            reasons.append({"code": "model_evidence_unavailable"})
        if separation_status == "converged":
            reasons.append({"code": "strategies_converged"})
        elif separation_status == "unstable":
            reasons.append({"code": "strategy_separation_unstable"})
        elif separation_status == "unknown" and not missing:
            reasons.append({"code": "strategy_separation_unknown"})
        codes = {reason["code"] for reason in reasons}
        if codes & {"strategy_missing", "run_invalid", "model_evidence_unavailable"}:
            priority = "high"
        elif codes & {
            "quality_gap",
            "resource_evidence_incomplete",
            "strategies_converged",
            "strategy_separation_unstable",
            "strategy_separation_unknown",
        }:
            priority = "medium"
        else:
            priority = "low"
            reasons = [{"code": "ready_for_confirmation"}]
        priorities.append(
            {
                "design": design,
                "family": rows[0]["family"],
                "priority": priority,
                "strategies_present": sorted(present),
                "strategies_missing": missing,
                "seed_count": len({row["seed"] for row in rows}),
                "expected_seed_count": len(seeds),
                "quality_levels": dict(sorted(quality.items())),
                "strategy_separation": separation_status,
                "model_evidence_available": model_available if model_rows else None,
                "reasons": reasons,
                "next_action": _next_action(codes),
            }
        )
    order = {"high": 0, "medium": 1, "low": 2}
    priorities.sort(key=lambda row: (order[row["priority"]], row["design"]))
    for rank, row in enumerate(priorities, 1):
        row["rank"] = rank
    return priorities


def _next_action(codes: set[str]) -> str:
    if "strategy_missing" in codes:
        return "complete_strategy_matrix"
    if "run_invalid" in codes:
        return "rerun_invalid_runs"
    if "model_evidence_unavailable" in codes:
        return "collect_model_evidence"
    if codes & {"quality_gap", "resource_evidence_incomplete"}:
        return "repair_evidence_coverage"
    if codes & {"strategies_converged", "strategy_separation_unknown"}:
        return "refreeze_and_expand_search"
    if "strategy_separation_unstable" in codes:
        return "repeat_matched_seeds"
    return "add_independent_confirmation"


def _search_actions(search: Any) -> list[dict[str, Any]]:
    if not isinstance(search, dict):
        return []
    coverage = search.get("space_coverage")
    if not isinstance(coverage, dict) or not isinstance(coverage.get("axes"), dict):
        return []
    actions = []
    for axis, entry in sorted(coverage["axes"].items()):
        if not isinstance(axis, str) or not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if not isinstance(status, str):
            continue
        action = {
            "lower_boundary": "expand_lower_bound",
            "upper_boundary": "expand_upper_bound",
            "boundary_only": "add_interior_values",
            "boundary_mixed": "expand_boundary_and_interior",
            "inconsistent_bounds": "freeze_one_axis_contract",
        }.get(status)
        if action is None:
            continue
        actions.append(
            {
                "code": "search_space_adjustment",
                "priority": "medium",
                "axis": axis,
                "status": status,
                "action": action,
                "lower_bound": entry.get("lower_bound"),
                "upper_bound": entry.get("upper_bound"),
                "selected_values": entry.get("selected_values"),
                "reason": (
                    "Re-freeze the axis and every strategy/seed plan before comparing the "
                    "next equal-budget round"
                ),
            }
        )
    return actions


def _coverage_actions(designs: int, families: int, seeds: int) -> list[dict[str, Any]]:
    actions = []
    if designs < MIN_DESIGNS:
        actions.append(
            {
                "code": "independent_design_coverage",
                "priority": "high",
                "current": designs,
                "required": MIN_DESIGNS,
                "reason": (
                    "Add designs outside the current evidence set; repeated seeds are not "
                    "new designs"
                ),
            }
        )
    if families < MIN_FAMILIES:
        actions.append(
            {
                "code": "family_coverage",
                "priority": "high",
                "current": families,
                "required": MIN_FAMILIES,
                "reason": (
                    "Add independent families; directory names must not be used as family "
                    "labels"
                ),
            }
        )
    if seeds < MIN_SEEDS:
        actions.append(
            {
                "code": "seed_coverage",
                "priority": "high",
                "current": seeds,
                "required": MIN_SEEDS,
                "reason": "Run every strategy under the same matched seed set",
            }
        )
    return actions


def _model_actions(model_evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(model_evidence, dict):
        return []
    calibration = model_evidence.get("calibration")
    if not isinstance(calibration, dict) or calibration.get("status") != "available":
        return [
            {
                "code": "model_calibration",
                "priority": "medium",
                "status": calibration.get("status") if isinstance(calibration, dict) else "unknown",
                "reason": (
                    "Run model-assisted trials with measured fresh QoR before comparing "
                    "calibration"
                ),
            }
        ]
    pair_count = calibration.get("pair_count")
    design_count = calibration.get("design_count")
    family_count = calibration.get("family_count")
    if (
        isinstance(pair_count, int)
        and pair_count >= 3
        and isinstance(design_count, int)
        and design_count >= 3
        and isinstance(family_count, int)
        and family_count >= 2
    ):
        return []
    return [
        {
            "code": "model_calibration",
            "priority": "medium",
            "status": "insufficient_evidence",
            "pair_count": pair_count,
            "design_count": design_count,
            "family_count": family_count,
            "reason": (
                "Calibration requires at least 3 selected predictions across 3 designs and "
                "2 families"
            ),
        }
    ]


def _per_run_limits(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limits = set()
    for row in runs:
        budget = row.get("budget")
        value = budget.get("limits") if isinstance(budget, dict) else None
        if isinstance(value, dict):
            limits.add(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return [json.loads(item) for item in sorted(limits)]


def _quality_level(row: dict[str, Any]) -> str:
    quality = row.get("quality")
    value = quality.get("level") if isinstance(quality, dict) else None
    return value if isinstance(value, str) else "unknown"


def _check(row: dict[str, Any], name: str) -> bool | None:
    quality = row.get("quality")
    checks = quality.get("checks") if isinstance(quality, dict) else None
    value = checks.get(name) if isinstance(checks, dict) else None
    return value if isinstance(value, bool) else None


def _model_status(row: dict[str, Any]) -> str:
    model = row.get("model")
    value = model.get("status") if isinstance(model, dict) else None
    return value if isinstance(value, str) else "unknown"


def _run_id(row: dict[str, Any]) -> str:
    return f"{row['design']}:{row['strategy']}:{row['seed']}"


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_benchmark_next_invalid")
