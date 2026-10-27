"""Recommend a search strategy only when equal-budget paired evidence supports it."""

from collections import defaultdict
from math import comb
from pathlib import Path
from typing import Any

from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.campaign import CAMPAIGN_MANIFEST_SCHEMA
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

ADVICE_SCHEMA = "ecc-experience-strategy-advice/1"
MIN_PAIRS = 6
MIN_P_VALUE = 0.05


def advise_strategy(
    manifest_path: str | Path,
    output: str | Path,
    *,
    direction: str = "minimize",
) -> dict[str, Any]:
    source = Path(manifest_path).expanduser().absolute()
    manifest = read_json(source, 64 * 1024 * 1024)
    if manifest.get("schema") != CAMPAIGN_MANIFEST_SCHEMA or not isinstance(
        manifest.get("runs"), list
    ):
        raise _invalid("Invalid campaign manifest")
    if direction not in {"minimize", "maximize"}:
        raise _invalid("Direction must be minimize or maximize")
    pairs = _pairs(manifest["runs"], direction)
    comparisons = {
        strategy: _comparison(values) for strategy, values in sorted(pairs.items()) if values
    }
    eligible = [
        (name, result)
        for name, result in comparisons.items()
        if result["pair_count"] >= MIN_PAIRS
        and result["wins"] > result["losses"]
        and result["sign_test_p"] is not None
        and result["sign_test_p"] <= MIN_P_VALUE
    ]
    recommended = (
        max(
            eligible,
            key=lambda item: (item[1]["wins"] - item[1]["losses"], -item[1]["sign_test_p"]),
        )[0]
        if eligible
        else "grid"
    )
    evidence = recommended != "grid"
    result = {
        "schema": ADVICE_SCHEMA,
        "manifest_sha256": digest(manifest),
        "recommended": recommended,
        "fallback": "grid",
        "confidence": "experimental" if evidence else "insufficient_evidence",
        "equal_budget": bool(manifest.get("budget", {}).get("equal_budget")),
        "comparisons": comparisons,
        "provenance": {
            "campaign_id": manifest.get("campaign_id"),
            "minimum_pairs": MIN_PAIRS,
            "maximum_sign_test_p": MIN_P_VALUE,
        },
        "promotion_allowed": False,
        "safe_to_apply": False,
        "reason": "Paired campaign evidence supports an experimental preference"
        if evidence
        else "No strategy has sufficient equal-budget paired evidence",
    }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise _invalid("Strategy advice output must be a new file")
    write_plan(destination, result)
    return result


def _pairs(runs: list[dict[str, Any]], direction: str) -> dict[str, list[int]]:
    grouped = defaultdict(dict)
    for row in runs:
        if row.get("final_qor") is None:
            continue
        grouped[(row.get("design"), row.get("seed"))][row.get("strategy")] = row["final_qor"]
    result = defaultdict(list)
    for values in grouped.values():
        baseline = values.get("grid")
        if baseline is None:
            continue
        for strategy, value in values.items():
            if strategy == "grid":
                continue
            if value < baseline:
                result[strategy].append(1 if direction == "minimize" else -1)
            elif value > baseline:
                result[strategy].append(-1 if direction == "minimize" else 1)
            else:
                result[strategy].append(0)
    return result


def _comparison(values: list[int]) -> dict[str, Any]:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = len(values) - wins - losses
    return {
        "pair_count": len(values),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "sign_test_p": _sign_test(wins, losses),
    }


def _sign_test(wins: int, losses: int) -> float | None:
    trials = wins + losses
    if trials == 0:
        return 1.0
    tail = sum(comb(trials, index) for index in range(min(wins, losses) + 1)) / 2**trials
    return min(1.0, 2 * tail)


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_strategy_invalid")
