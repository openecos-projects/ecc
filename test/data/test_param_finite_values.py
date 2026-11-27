"""Parameter values have to be finite numbers."""

import math

import pytest

from chipcompiler.data.parameter_schema import (
    ParamSchema,
    list_schemas,
    lookup_schema,
    validate_value,
)

_RANGED = ["design.frequency_mhz", "floorplan.core_util", "place.target_density"]
_UNRANGED = "floorplan.macro_placer.macro_placement_halo"


def _schema(param: str) -> ParamSchema:
    schema = lookup_schema(param)
    assert schema is not None
    return schema


@pytest.mark.parametrize("param", _RANGED)
def test_nan_is_not_inside_a_range(param):
    schema = _schema(param)

    assert validate_value(math.nan, schema) == [f"value nan is not a finite number for {param}"]


@pytest.mark.parametrize("param", _RANGED)
@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_an_infinity_stays_an_out_of_range_value(param, value):
    schema = _schema(param)

    errors = validate_value(value, schema)

    assert len(errors) == 1
    assert "out of range" in errors[0]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_parameter_without_a_range_refuses_non_finite_numbers(value):
    schema = _schema(_UNRANGED)
    assert schema.type == "float"
    assert schema.range is None

    assert validate_value(value, schema) == [
        f"value {value} is not a finite number for {_UNRANGED}"
    ]
    assert validate_value(2.5, schema) == []


@pytest.mark.parametrize("value", [[math.nan, 2.0], [2.0, math.inf], [-math.inf]])
def test_a_list_refuses_non_finite_elements(value):
    schema = _schema("floorplan.core_margin")

    assert validate_value(value, schema) == [
        f"value {value} contains a non-finite number for floorplan.core_margin"
    ]
    assert validate_value([2.0, 3.0], schema) == []


def test_every_default_is_still_valid():
    """No shipped default is a NaN or an infinity."""
    for schema in list_schemas():
        if schema.type in {"float", "list[float]"} and schema.default is not None:
            assert [e for e in validate_value(schema.default, schema) if "finite" in e] == []
