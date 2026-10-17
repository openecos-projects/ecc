from copy import deepcopy

from ecc_experience.dse.optimizer import propose


def optimizer_plan():
    objective = {"id": "core_area", "unit": "um^2", "direction": "minimize"}
    return {
        "strategy": "adaptive",
        "algorithm": {"name": "categorical_tpe", "version": 1, "seed": 42},
        "space": {
            "floorplan.core_util": [0.25, 0.3, 0.35, 0.4],
            "floorplan.aspect_ratio": [1, 2, 3, 4],
        },
        "rungs": [{"objectives": [objective]}],
        "warm_start": {"seeds": []},
    }


def test_adaptive_replay_is_deterministic_and_observation_driven():
    plan = optimizer_plan()
    history, decisions = [], []
    for index in range(10):
        proposed, decision = propose(plan, history)
        assert (proposed, decision) == propose(deepcopy(plan), deepcopy(history))
        assert proposed["parameters"] not in [trial["parameters"] for trial in history]
        decisions.append(decision)
        history.append(
            {
                **proposed,
                "status": "blocked" if index == 1 else "stage_passed",
                "objective_values": None if index == 1 else [100 - index],
            }
        )
    assert decisions[0]["reason"] == "space_center"
    assert decisions[-1]["reason"] == "categorical_density_ratio"
    assert history[1]["candidate_id"] not in decisions[-1]["good_trials"]
    changed = deepcopy(history[:-1])
    changed[0]["objective_values"] = [1]
    assert propose(plan, changed)[1]["history_sha256"] != decisions[-1]["history_sha256"]


def test_warm_seed_provenance_grid_order_and_space_exhaustion():
    plan = optimizer_plan()
    seed = {
        "parameters": {"floorplan.core_util": 0.25, "floorplan.aspect_ratio": 1},
        "case_id": "observed-case",
        "distance": 0.0,
    }
    plan["warm_start"]["seeds"] = [seed]
    proposed, decision = propose(plan, [])
    assert proposed["parameters"] == seed["parameters"]
    assert decision["provenance"] == seed
    plan["strategy"] = "grid"
    history = []
    for _index in range(16):
        proposed, _decision = propose(plan, history)
        history.append({**proposed, "status": "failed", "objective_values": None})
    assert len({str(trial["parameters"]) for trial in history}) == 16
    assert propose(plan, history)[0] is None
