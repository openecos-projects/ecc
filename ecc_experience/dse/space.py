"""Bounded, validated discrete search domains used by frozen DSE plans."""

import itertools
import json
import math
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from chipcompiler.data.parameter_schema import lookup_schema, parse_cli_overrides
from ecc_experience.dse.plan import STAGE_PARAMETERS, invalid
from ecc_experience.optimization.policy import validate_reviewed_values


class Axis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    values: list[JsonValue] | None = Field(default=None, min_length=1, max_length=10000)
    range: list[float] | None = Field(default=None, min_length=2, max_length=2)
    step: float | None = None


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
        if axis.values is not None:
            if axis.range is not None or axis.step is not None:
                raise invalid("Each axis requires values or range/step")
            values = axis.values
        else:
            if axis.range is None or axis.step is None or axis.step <= 0:
                raise invalid("A range requires two bounds and a positive step")
            start, stop = (Decimal(str(value)) for value in axis.range)
            step = Decimal(str(axis.step))
            count = int((stop - start) // step) + 1
            if stop < start or not 1 <= count <= 10000:
                raise invalid("Range bounds or cardinality are invalid")
            range_values = [float(start + index * step) for index in range(count)]
            values = range_values
            schema = lookup_schema(key)
            if schema is not None and schema.type == "int":
                values = [int(value) if value == int(value) else value for value in range_values]
        normalized = [candidate({key: value}, "validation")["parameters"][key] for value in values]
        if len({literal(value) for value in normalized}) != len(normalized):
            raise invalid("Axis values must be unique after ECC type normalization")
        result[key] = normalized
    if math.prod(len(values) for values in result.values()) > 100000:
        raise invalid("Discrete search space exceeds 100000 configurations")
    return result


def grid_candidates(space: dict[str, list]) -> list[dict]:
    keys = sorted(space)
    return [
        candidate(dict(zip(keys, values, strict=True)), f"candidate-{index:04d}")
        for index, values in enumerate(itertools.product(*(space[key] for key in keys)), 1)
    ]
