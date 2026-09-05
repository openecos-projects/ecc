"""Schema and TOML editing for project declarations in ``ecc.toml``."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ProjectField:
    key: str
    table: str
    name: str
    type: str
    list_value: bool = False


PROJECT_FIELDS = (
    ProjectField("design.name", "design", "name", "str"),
    ProjectField("design.top", "design", "top", "str"),
    ProjectField("design.rtl", "design", "rtl", "str", list_value=True),
    ProjectField("design.netlist", "design", "netlist", "str"),
    ProjectField("design.golden_netlist", "design", "golden_netlist", "str"),
    ProjectField("design.def", "design", "def", "str"),
    ProjectField("design.sdc", "design", "sdc", "str"),
    ProjectField("design.spef", "design", "spef", "str"),
    ProjectField("design.clock_port", "design", "clock_port", "str"),
    ProjectField("design.frequency_mhz", "design", "frequency_mhz", "float"),
    ProjectField("pdk.name", "pdk", "name", "str"),
    ProjectField("pdk.root", "pdk", "root", "str"),
    ProjectField("flow.preset", "flow", "preset", "str"),
)

_FIELD_INDEX = {field.key: field for field in PROJECT_FIELDS}


def lookup_project_field(key: str) -> ProjectField | None:
    return _FIELD_INDEX.get(key)


def parse_project_field_values(
    field: ProjectField, values: tuple[str, ...]
) -> str | float | list[str]:
    if field.list_value:
        if not values or any(not value.strip() for value in values):
            raise ValueError(f"{field.key} requires one or more non-empty values")
        return list(values)
    if len(values) != 1:
        raise ValueError(f"{field.key} requires exactly one value")
    value = values[0].strip()
    if not value:
        raise ValueError(f"{field.key} must not be empty")
    if field.type == "float":
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(f"{field.key} must be a number") from exc
        if not isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{field.key} must be greater than zero")
        return parsed
    return value
