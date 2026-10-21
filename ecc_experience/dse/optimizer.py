"""Deterministic discrete TPE proposals with feasibility-aware observed history."""

import itertools
import math
import random

from ecc_experience.dse.multiobjective import rank_trials
from ecc_experience.dse.space import candidate
from ecc_experience.files import digest


def history_facts(history: list[dict]) -> list[dict]:
    return [
        {
            key: trial.get(key)
            for key in ("candidate_id", "parameters", "status", "objective_values")
        }
        for trial in history
    ]


def propose(plan: dict, history: list[dict]) -> tuple[dict | None, dict]:
    facts = history_facts(history)
    identity = digest(facts)
    algorithm = plan["algorithm"]
    seed = int(digest({"algorithm": algorithm, "history": identity}), 16)
    generator = random.Random(seed)
    used = [trial["parameters"] for trial in history]
    space = plan["space"]
    keys = sorted(space)
    available = [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(space[key] for key in keys))
        if dict(zip(keys, values, strict=True)) not in used
    ]
    decision = {"algorithm": algorithm, "history_sha256": identity, "source": "grid"}
    if not available:
        return None, {**decision, "reason": "space_exhausted"}
    selected = None
    if plan["strategy"] == "grid":
        selected = available[0]
    else:
        seeds = plan["warm_start"]["seeds"]
        selected_seed = next((item for item in seeds if item["parameters"] not in used), None)
        if selected_seed:
            selected = selected_seed["parameters"]
            decision.update(source="warm_start", provenance=selected_seed)
        elif not history:
            selected = {key: values[len(values) // 2] for key, values in space.items()}
            decision.update(source="adaptive", reason="space_center")
        else:
            ranking = rank_trials(history, plan["rungs"][0]["objectives"])
            good_count = min(len(ranking), max(1, math.ceil(len(history) * 0.25)))
            good_ids = {item["id"] for item in ranking[:good_count]}
            good = [trial["parameters"] for trial in history if trial["candidate_id"] in good_ids]
            bad = [
                trial["parameters"] for trial in history if trial["candidate_id"] not in good_ids
            ]
            pool = generator.sample(available, min(len(available), 128))
            if len(history) < 6 or len(good) < 2 or not bad:
                selected = generator.choice(pool)
                decision.update(source="adaptive", reason="startup_uniform")
            else:

                def ratio(parameters):
                    score = 0.0
                    for key, values in space.items():
                        good_probability = (
                            1 + sum(row[key] == parameters[key] for row in good)
                        ) / (len(good) + len(values))
                        bad_probability = (1 + sum(row[key] == parameters[key] for row in bad)) / (
                            len(bad) + len(values)
                        )
                        score += math.log(good_probability / bad_probability)
                    return -score, digest(parameters)

                selected = min(pool, key=ratio)
                decision.update(
                    source="adaptive",
                    reason="categorical_density_ratio",
                    good_trials=sorted(good_ids),
                    pool_size=len(pool),
                )
    proposed = candidate(selected, f"candidate-{len(history) + 1:04d}")
    return proposed, {**decision, "candidate": proposed}
