"""Compare measured objectives without replacing prefix or final signoff gates."""

from chipcompiler.analysis.pareto import Objective, rank_points
from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY
from ecc_experience.dse.plan import invalid
from ecc_experience.knowledge.features import case_features

DSE_OBJECTIVE_METRICS = {
    **METRIC_REGISTRY,
    "std_cell_area": ("um^2", "lower_is_better"),
}


def resolve_objectives(specs: list[dict], features: dict) -> list[dict]:
    selected = []
    for spec in specs:
        metric = spec["metric"]
        registered = DSE_OBJECTIVE_METRICS.get(metric)
        polarity = "lower_is_better" if spec["direction"] == "minimize" else "higher_is_better"
        if registered is None or registered != (spec["unit"], polarity):
            raise invalid(
                "Objective ID, unit and direction must match the supported DSE metric registry"
            )
        step = spec.get("step") or features["steps"][-1]["step"]
        matching = [
            item
            for entry in features["steps"]
            if entry["step"] == step
            for item in entry["metrics"]
            if item["id"] == metric
            and item["unit"] == spec["unit"]
            and item["status"] == "available"
            and (spec.get("scope") is None or item["scope"] == spec["scope"])
            and (spec.get("corner") is None or item["corner"] == spec["corner"])
        ]
        if len(matching) != 1:
            raise invalid(
                "Each objective must identify one available baseline metric in the prefix"
            )
        selected.append(
            {
                "step": step,
                "direction": spec["direction"],
                **{key: matching[0][key] for key in ("id", "unit", "scope", "corner")},
            }
        )
    if len({item["id"] for item in selected}) != len(selected):
        raise invalid("Objectives must be unique")
    return selected


def measure_objectives(case_id: str, store, through_step: str, objectives: list[dict]) -> dict:
    features = case_features(case_id, store, through_step=through_step)
    evidence = []
    for objective in objectives:
        found = [
            metric
            for step in features["steps"]
            if step["step"] == objective["step"]
            for metric in step["metrics"]
            if metric["status"] == "available"
            and all(metric.get(key) == objective[key] for key in ("id", "unit", "scope", "corner"))
        ]
        if len(found) != 1:
            return {"status": "unknown", "values": None, "evidence": evidence}
        evidence.append(found[0])
    return {
        "status": "available",
        "values": [item["value"] for item in evidence],
        "evidence": evidence,
    }


def rank_trials(trials: list[dict], objectives: list[dict]) -> list[dict]:
    points = {
        trial["candidate_id"]: trial["objective_values"]
        for trial in trials
        if trial["status"] == "stage_passed" and trial.get("objective_values") is not None
    }
    return rank_points(
        points, [Objective(item["id"], item["unit"], item["direction"]) for item in objectives]
    )
