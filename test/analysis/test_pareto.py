import pytest

from chipcompiler.analysis.pareto import Objective, rank_points


def test_tradeoffs_dominance_and_equal_points_have_stable_fronts():
    objectives = [Objective("area", "um^2", "minimize"), Objective("speed", "MHz", "maximize")]
    points = {
        "large-fast": [20, 200],
        "small-slow": [10, 100],
        "dominated": [21, 100],
        "equal": [10, 100],
        "balanced": [15, 150],
    }

    ranked = rank_points(points, objectives)

    assert {row["id"] for row in ranked if row["rank"] == 0} == {
        "large-fast",
        "small-slow",
        "equal",
        "balanced",
    }
    assert ranked[-1]["id"] == "dominated"
    assert ranked == rank_points(dict(reversed(list(points.items()))), objectives)


@pytest.mark.parametrize("values", [[None, 1], [float("nan"), 1], [True, 1], [1]])
def test_invalid_vectors_cannot_enter_front(values):
    with pytest.raises(ValueError, match="finite"):
        rank_points(
            {"bad": values},
            [Objective("area", "um^2", "minimize"), Objective("delay", "ns", "minimize")],
        )


def test_constant_objective_does_not_artificially_prefer_endpoints():
    assert rank_points({"b": [1], "a": [1]}, [Objective("x", "ratio", "minimize")]) == [
        {"id": "a", "rank": 0, "crowding_distance": 0.0},
        {"id": "b", "rank": 0, "crowding_distance": 0.0},
    ]
