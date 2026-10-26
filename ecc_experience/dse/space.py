"""Bounded, validated discrete search domains used by frozen DSE plans."""

import itertools
import json
import math
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from chipcompiler.data.parameter_schema import lookup_schema, parse_cli_overrides
from ecc_experience.dse.plan import STAGE_PARAMETERS, invalid
from ecc_experience.optimization.policy import validate_reviewed_values


class Axis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    values: list[JsonValue] | None = Field(default=None, min_length=1, max_length=10000)
    range: list[float] | None = Field(default=None, min_length=2, max_length=2)
    step: float | None = None
    kind: Literal["values", "range"] | None = None
    min: float | None = None
    max: float | None = None
    scale: Literal["linear", "log"] = "linear"
    points: int | None = Field(default=None, ge=2, le=100)


def literal(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, allow_nan=False)


def candidate(parameters: dict, identity: str) -> dict:
    try:
        sets = [f"{key}={literal(value)}" for key, value in sorted(parameters.items())]
    except (TypeError, ValueError) as exc:
        raise invalid("DSE parameters require finite JSON values") from exc
    parsed, errors = parse_cli_overrides(sets)
    if errors:
        raise invalid("; ".join(errors))
    validate_reviewed_values(parsed, {})
    return {"candidate_id": identity, "parameters": parsed, "sets": sets}


def expand_space(space: dict[str, Axis]) -> dict[str, list]:
    if not space or not set(space) <= STAGE_PARAMETERS:
        raise invalid("Space requires reviewed ECC parameters")
    result = {}
    for key, axis in sorted(space.items()):
        values = _axis_values(key, axis)
        normalized = [candidate({key: value}, "validation")["parameters"][key] for value in values]
        if len({literal(value) for value in normalized}) != len(normalized):
            raise invalid("Axis values must be unique after ECC type normalization")
        result[key] = normalized
    if math.prod(len(values) for values in result.values()) > 100000:
        raise invalid("Discrete search space exceeds 100000 configurations")
    return result


def _axis_values(key: str, axis: Axis) -> list:
    range_fields = (axis.range, axis.step, axis.min, axis.max, axis.points)
    if axis.values is not None:
        if axis.kind not in {None, "values"} or any(value is not None for value in range_fields):
            raise invalid("Each axis requires values or a range, not both")
        return axis.values
    if axis.kind == "values":
        raise invalid("A values axis requires values")
    if axis.range is not None:
        if axis.min is not None or axis.max is not None or axis.kind not in {None, "range"}:
            raise invalid("Use either range bounds or min/max, not both")
        if axis.step is None or axis.step <= 0:
            raise invalid("A range requires two bounds and a positive step")
        start, stop = (Decimal(str(value)) for value in axis.range)
        step = Decimal(str(axis.step))
        count = int((stop - start) // step) + 1
        if stop < start or not 1 <= count <= 10000:
            raise invalid("Range bounds or cardinality are invalid")
        return _normalize_numeric_axis(key, [float(start + index * step) for index in range(count)])
    if axis.min is None or axis.max is None or axis.min > axis.max:
        raise invalid("A range requires finite min/max bounds in ascending order")
    if axis.min == axis.max:
        return _normalize_numeric_axis(key, [axis.min])
    if axis.step is not None and axis.scale != "linear":
        raise invalid("A logarithmic range cannot use an additive step")
    if axis.step is not None:
        if axis.step <= 0:
            raise invalid("A range step must be positive")
        count = int((axis.max - axis.min) // axis.step) + 1
        if not 1 <= count <= 10000:
            raise invalid("Range cardinality is invalid")
        return _normalize_numeric_axis(
            key, [axis.min + index * axis.step for index in range(count)]
        )
    points = axis.points or 9
    if axis.scale == "log" and axis.min <= 0:
        raise invalid("A logarithmic range requires positive bounds")
    if axis.scale == "log":
        low, high = math.log(axis.min), math.log(axis.max)
        values = [math.exp(low + (high - low) * index / (points - 1)) for index in range(points)]
    else:
        values = [
            axis.min + (axis.max - axis.min) * index / (points - 1) for index in range(points)
        ]
    return _normalize_numeric_axis(key, values)


def _normalize_numeric_axis(key: str, values: list[float]) -> list:
    schema = lookup_schema(key)
    if schema is not None and schema.type == "int":
        values = [int(round(value)) for value in values]
    normalized = []
    seen = set()
    for value in values:
        marker = literal(value)
        if marker not in seen:
            normalized.append(value)
            seen.add(marker)
    return normalized


def grid_candidates(space: dict[str, list]) -> list[dict]:
    keys = sorted(space)
    return [
        candidate(dict(zip(keys, values, strict=True)), f"candidate-{index:04d}")
        for index, values in enumerate(itertools.product(*(space[key] for key in keys)), 1)
    ]
