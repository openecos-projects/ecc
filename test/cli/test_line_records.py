"""Grammar contract for the narrow line-record queries (extend_cli §4.3.1)."""

import json
import math
from collections.abc import Mapping

import pytest

from chipcompiler.cli.core import line_records
from chipcompiler.cli.core.line_records import (
    LineRecordError,
    json_literal,
    serialize_line_record,
    serialize_line_records,
)


class _DuplicateKeys(Mapping):
    """A Mapping whose iteration yields a key twice (plain dicts cannot)."""

    def __iter__(self):
        return iter(("record", "a", "a"))

    def __len__(self):
        return 3

    def __getitem__(self, key):
        return {"record": "x", "a": "1"}[key]


def test_safe_values_stay_bare():
    value = "AZaz09._:/+@-"
    assert serialize_line_record({"record": "flow_step", "v": value}) == (
        f"record=flow_step v={value}"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("has space", '"has space"'),
        ("comma,", '"comma,"'),
        ("equal=sign", '"equal=sign"'),
        ("uniçode", '"uniçode"'),
        ("", '""'),
    ],
)
def test_values_outside_safe_set_are_quoted(value, expected):
    assert serialize_line_record({"record": "flow_step", "v": value}) == (
        f"record=flow_step v={expected}"
    )


@pytest.mark.parametrize(
    ("value", "escaped"),
    [
        ("back\\slash", "back\\\\slash"),
        ('say "hi"', 'say \\"hi\\"'),
        ("line\nbreak", "line\\nbreak"),
        ("carriage\rreturn", "carriage\\rreturn"),
        ("tab\there", "tab\\there"),
    ],
)
def test_only_the_five_escapes_are_used(value, escaped):
    assert serialize_line_record({"record": "flow_step", "v": value}) == (
        f'record=flow_step v="{escaped}"'
    )


def test_round_trip_through_quoting_and_escapes():
    value = 'p\\a"th\nwith\ttabs\r'
    line = serialize_line_record({"record": "flow_step", "v": value})
    encoded = line.split("=", 2)[2].strip('"')
    assert json.loads(f'"{encoded}"') == value


def test_duplicate_key_fails_the_record():
    with pytest.raises(LineRecordError, match="duplicate"):
        serialize_line_record(_DuplicateKeys())


def test_record_must_be_the_first_field():
    with pytest.raises(LineRecordError, match="first field"):
        serialize_line_record({"v": "x", "record": "flow_step"})
    with pytest.raises(LineRecordError, match="first field"):
        serialize_line_record({})


def test_booleans_ints_floats_and_omitted_none():
    line = serialize_line_record(
        {"record": "flow_step", "flag": True, "n": -3, "ratio": 0.5, "skip": None}
    )
    assert line == "record=flow_step flag=true n=-3 ratio=0.5"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_floats_are_rejected(bad):
    with pytest.raises(LineRecordError, match="non-finite"):
        serialize_line_record({"record": "flow_step", "v": bad})
    with pytest.raises(ValueError):
        json_literal(bad)


def test_json_literal_is_compact_and_finite():
    assert json_literal({"a": [1, 2]}) == '{"a":[1,2]}'
    assert json.loads(json_literal({"a": [1, 2]})) == {"a": [1, 2]}


def test_per_record_line_limit(monkeypatch):
    monkeypatch.setattr(line_records, "MAX_LINE_BYTES", 16)
    with pytest.raises(LineRecordError, match="exceeds 16 bytes"):
        serialize_line_records([{"record": "flow_step", "v": "x" * 32}])


def test_aggregate_output_limit(monkeypatch):
    monkeypatch.setattr(line_records, "MAX_OUTPUT_BYTES", 64)
    records = [{"record": "flow_step", "v": "x" * 32} for _ in range(4)]
    with pytest.raises(LineRecordError, match="output exceeds 64"):
        serialize_line_records(records)


def test_record_count_limit(monkeypatch):
    monkeypatch.setattr(line_records, "MAX_RECORDS", 2)
    records = [{"record": "flow_step", "step": str(index)} for index in range(3)]
    with pytest.raises(LineRecordError, match="limit exceeds 2"):
        serialize_line_records(records)


def test_unsupported_value_type_is_rejected():
    with pytest.raises(LineRecordError, match="unsupported"):
        serialize_line_record({"record": "flow_step", "v": ["not", "a", "string"]})
