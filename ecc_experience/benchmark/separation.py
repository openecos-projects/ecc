"""Compare final selections within each design and seed."""

from collections import defaultdict
from typing import Any

from ecc_experience.files import digest


def analyze_strategy_separation(
    rows: list[dict[str, Any]], strategies: tuple[str, ...]
) -> dict[str, Any]:
    expected = set(strategies)
    grouped: dict[str, dict[Any, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        design = row.get("design")
        seed = row.get("seed")
        strategy = row.get("strategy")
        parameters = row.get("selected_parameters")
        if (
            row.get("status") != "complete"
            or not isinstance(design, str)
            or not design
            or seed is None
            or isinstance(seed, bool)
            or strategy not in expected
            or not isinstance(parameters, dict)
        ):
            continue
        grouped[design][seed][strategy] = digest(parameters)

    seed_groups = []
    separated = []
    converged = []
    unstable = []
    unknown = []
    for design in sorted(grouped):
        statuses = []
        for seed in sorted(grouped[design], key=str):
            selections = grouped[design][seed]
            complete = set(selections) == expected
            distinct = len(set(selections.values())) if complete else None
            status = (
                "unknown"
                if not complete
                else "separated"
                if distinct is not None and distinct > 1
                else "converged"
            )
            statuses.append(status)
            seed_groups.append(
                {
                    "design": design,
                    "seed": seed,
                    "status": status,
                    "strategy_count": len(selections),
                    "distinct_selections": distinct,
                }
            )
        if not statuses or "unknown" in statuses:
            unknown.append(design)
        elif set(statuses) == {"separated"}:
            separated.append(design)
        elif set(statuses) == {"converged"}:
            converged.append(design)
        else:
            unstable.append(design)

    return {
        "status": "separated" if separated else "converged" if converged else "unknown",
        "comparison_unit": "design_seed_strategy",
        "separated_designs": separated,
        "converged_designs": converged,
        "unstable_designs": unstable,
        "unknown_designs": unknown,
        "seed_groups": seed_groups,
    }
