"""Deterministic non-dominated sorting for finite, comparable objective vectors."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Objective:
    id: str
    unit: str
    direction: str

    def __post_init__(self):
        if not self.id or not self.unit or self.direction not in {"minimize", "maximize"}:
            raise ValueError("Objective requires an ID, unit and minimize/maximize direction")


def rank_points(points: dict[str, list[float]], objectives: list[Objective]) -> list[dict]:
    if not 1 <= len(objectives) <= 3 or len({item.id for item in objectives}) != len(objectives):
        raise ValueError("Provide one to three unique objectives")
    normalized = {}
    for identity, values in points.items():
        if len(values) != len(objectives) or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise ValueError("Pareto points require a finite value for every objective")
        normalized[identity] = [
            value if objective.direction == "minimize" else -value
            for value, objective in zip(values, objectives, strict=True)
        ]
    remaining = set(points)
    ranked = []
    rank = 0
    while remaining:
        front = sorted(
            identity
            for identity in remaining
            if not any(
                _dominates(normalized[other], normalized[identity])
                for other in remaining
                if other != identity
            )
        )
        distances = _crowding(front, normalized, len(objectives))
        ranked.extend(
            {"id": identity, "rank": rank, "crowding_distance": distances[identity]}
            for identity in sorted(
                front,
                key=lambda key: (
                    -(distances[key] if distances[key] is not None else math.inf),
                    key,
                ),
            )
        )
        remaining.difference_update(front)
        rank += 1
    return ranked


def _dominates(left: list[float], right: list[float]) -> bool:
    return all(first <= second for first, second in zip(left, right, strict=True)) and any(
        first < second for first, second in zip(left, right, strict=True)
    )


def _crowding(front: list[str], points: dict[str, list[float]], dimensions: int) -> dict:
    distances: dict[str, float | None] = dict.fromkeys(front, 0.0)
    for dimension in range(dimensions):
        ordered = sorted(front, key=lambda identity: (points[identity][dimension], identity))
        low, high = points[ordered[0]][dimension], points[ordered[-1]][dimension]
        if high == low:
            continue
        distances[ordered[0]] = distances[ordered[-1]] = None
        for index in range(1, len(ordered) - 1):
            identity = ordered[index]
            distance = distances[identity]
            if distance is not None:
                distances[identity] = distance + (
                    points[ordered[index + 1]][dimension] - points[ordered[index - 1]][dimension]
                ) / (high - low)
    return distances
