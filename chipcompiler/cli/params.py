from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParamSchema:
    param: str
    group: str
    name: str
    type: str
    default: object
    applies: str
    maps_to: str | dict
    description: str
    range: tuple[float, float] | None = None
    choices: tuple[str, ...] | None = None
    unit: str | None = None
    example: str | None = None


PARAM_REGISTRY: tuple[ParamSchema, ...] = (
    ParamSchema(
        param="design.frequency_mhz",
        group="design",
        name="frequency_mhz",
        type="float",
        default=100.0,
        applies="synthesis",
        maps_to="Frequency max [MHz]",
        description="Target clock frequency in MHz",
        range=(1e-6, 10000.0),
        unit="MHz",
        example="200.0",
    ),
    ParamSchema(
        param="floorplan.core_util",
        group="floorplan",
        name="core_util",
        type="float",
        default=0.4,
        applies="floorplan",
        maps_to={"Core": "Utilitization"},
        description="Core utilization ratio",
        range=(0.01, 1.0),
        example="0.45",
    ),
    ParamSchema(
        param="floorplan.core_margin",
        group="floorplan",
        name="core_margin",
        type="list[int]",
        default=[2, 2],
        applies="floorplan",
        maps_to={"Core": "Margin"},
        description="Core margin in micrometers [horizontal, vertical]",
        example="[2, 2]",
    ),
    ParamSchema(
        param="floorplan.aspect_ratio",
        group="floorplan",
        name="aspect_ratio",
        type="float",
        default=1.0,
        applies="floorplan",
        maps_to={"Core": "Aspect ratio"},
        description="Core aspect ratio (width/height)",
        range=(0.1, 10.0),
        example="1.0",
    ),
    ParamSchema(
        param="synth.max_fanout",
        group="synth",
        name="max_fanout",
        type="int",
        default=20,
        applies="fixfanout",
        maps_to="Max fanout",
        description="Maximum fanout for netlist optimization",
        range=(1, 200),
        example="16",
    ),
    ParamSchema(
        param="place.target_density",
        group="place",
        name="target_density",
        type="float",
        default=0.3,
        applies="placement",
        maps_to={"DreamPlace": "target_density"},
        description="Target placement density",
        range=(0.1, 0.95),
        example="0.65",
    ),
    ParamSchema(
        param="place.target_overflow",
        group="place",
        name="target_overflow",
        type="float",
        default=0.1,
        applies="placement",
        maps_to={"DreamPlace": "stop_overflow"},
        description="Target overflow for global placement",
        range=(0.0, 1.0),
        example="0.08",
    ),
    ParamSchema(
        param="place.global_right_padding",
        group="place",
        name="global_right_padding",
        type="int",
        default=0,
        applies="placement",
        maps_to="Global right padding",
        description="Global right padding for placement sites",
        range=(0, 100),
        example="8",
    ),
    ParamSchema(
        param="place.cell_padding_x",
        group="place",
        name="cell_padding_x",
        type="int",
        default=600,
        applies="placement",
        maps_to={"DreamPlace": "cell_padding_x"},
        description="Cell padding in x-direction in database units",
        range=(0, 10000),
        example="400",
    ),
    ParamSchema(
        param="place.routability_opt",
        group="place",
        name="routability_opt",
        type="int",
        default=1,
        applies="placement",
        maps_to={"DreamPlace": "routability_opt_flag"},
        description="Enable routability-driven placement optimization",
        choices=("0", "1"),
        example="1",
    ),
    ParamSchema(
        param="route.bottom_layer",
        group="route",
        name="bottom_layer",
        type="str",
        default="MET2",
        applies="routing",
        maps_to="Bottom layer",
        description="Bottom routing layer",
        choices=("MET1", "MET2", "MET3", "MET4", "MET5"),
        example="MET2",
    ),
    ParamSchema(
        param="route.top_layer",
        group="route",
        name="top_layer",
        type="str",
        default="MET5",
        applies="routing",
        maps_to="Top layer",
        description="Top routing layer",
        choices=("MET2", "MET3", "MET4", "MET5", "MET6"),
        example="MET5",
    ),
)

_REGISTRY_INDEX: dict[str, ParamSchema] = {s.param: s for s in PARAM_REGISTRY}
_REQUIRED_FIELDS = ("param", "group", "name", "type", "default", "applies", "maps_to", "description")


def lookup_schema(key: str) -> ParamSchema | None:
    return _REGISTRY_INDEX.get(key)


def list_schemas() -> tuple[ParamSchema, ...]:
    return PARAM_REGISTRY


def list_groups() -> list[str]:
    seen: list[str] = []
    for s in PARAM_REGISTRY:
        if s.group not in seen:
            seen.append(s.group)
    return seen


def is_known_key(key: str) -> bool:
    return key in _REGISTRY_INDEX


def validate_schema_record(schema: ParamSchema) -> list[str]:
    errors: list[str] = []
    for f in _REQUIRED_FIELDS:
        if not getattr(schema, f, None):
            errors.append(f"missing required field: {f}")
    return errors


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

def parse_value(raw: str, schema: ParamSchema) -> object:
    ptype = schema.type

    if ptype == "int":
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"expected int for {schema.param}, got '{raw}'")

    if ptype == "float":
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"expected float for {schema.param}, got '{raw}'")

    if ptype == "bool":
        low = raw.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise ValueError(f"expected bool for {schema.param}, got '{raw}'")

    if ptype == "str":
        return raw

    if ptype == "list[int]":
        stripped = raw.strip("[]() ")
        if not stripped:
            return []
        parts = [p.strip() for p in stripped.split(",")]
        try:
            return [int(p) for p in parts if p]
        except ValueError:
            raise ValueError(f"expected list[int] for {schema.param}, got '{raw}'")

    if ptype == "list[float]":
        stripped = raw.strip("[]() ")
        if not stripped:
            return []
        parts = [p.strip() for p in stripped.split(",")]
        try:
            return [float(p) for p in parts if p]
        except ValueError:
            raise ValueError(f"expected list[float] for {schema.param}, got '{raw}'")

    if ptype == "list[str]":
        stripped = raw.strip("[]() ")
        if not stripped:
            return []
        return [p.strip() for p in stripped.split(",") if p.strip()]

    raise ValueError(f"unsupported type '{ptype}' for {schema.param}")


def validate_value(value: object, schema: ParamSchema) -> list[str]:
    errors: list[str] = []

    if schema.range is not None:
        lo, hi = schema.range
        if isinstance(value, (int, float)):
            if value < lo or value > hi:
                errors.append(f"value {value} out of range [{lo}, {hi}] for {schema.param}")

    if schema.choices is not None:
        str_val = str(value)
        if str_val not in schema.choices:
            errors.append(f"value '{str_val}' not in allowed choices {schema.choices} for {schema.param}")

    return errors


# ---------------------------------------------------------------------------
# Source-aware resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedParam:
    param: str
    value: object
    default: object
    source: str
    schema: ParamSchema


def _validate_toml_type(value: object, schema: ParamSchema) -> tuple[object, str | None]:
    ptype = schema.type
    key = schema.param

    if ptype == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return value, f"expected int for {key}, got {type(value).__name__}"
        return value, None

    if ptype == "float":
        if isinstance(value, bool):
            return value, f"expected float for {key}, got bool"
        if isinstance(value, (int, float)):
            return float(value), None
        return value, f"expected float for {key}, got {type(value).__name__}"

    if ptype == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            low = value.lower()
            if low in ("true", "1", "yes"):
                return True, None
            if low in ("false", "0", "no"):
                return False, None
        return value, f"expected bool for {key}, got {type(value).__name__}"

    if ptype == "str":
        if isinstance(value, str):
            return value, None
        return value, f"expected str for {key}, got {type(value).__name__}"

    if ptype == "list[int]":
        if not isinstance(value, list):
            return value, f"expected list for {key}, got {type(value).__name__}"
        for i, v in enumerate(value):
            if isinstance(v, bool) or not isinstance(v, int):
                return value, f"expected list[int] for {key}, element {i} is {type(v).__name__}"
        return value, None

    if ptype == "list[float]":
        if not isinstance(value, list):
            return value, f"expected list for {key}, got {type(value).__name__}"
        for i, v in enumerate(value):
            if isinstance(v, bool):
                return value, f"expected list[float] for {key}, element {i} is bool"
            if not isinstance(v, (int, float)):
                return value, f"expected list[float] for {key}, element {i} is {type(v).__name__}"
        return [float(v) for v in value], None

    if ptype == "list[str]":
        if not isinstance(value, list):
            return value, f"expected list for {key}, got {type(value).__name__}"
        for i, v in enumerate(value):
            if not isinstance(v, str):
                return value, f"expected list[str] for {key}, element {i} is {type(v).__name__}"
        return value, None

    return value, None


def resolve_parameters(
    toml_overrides: dict[str, object] | None = None,
    cli_overrides: dict[str, object] | None = None,
) -> tuple[list[ResolvedParam], list[str]]:
    toml_overrides = toml_overrides or {}
    cli_overrides = cli_overrides or {}
    resolved: list[ResolvedParam] = []
    errors: list[str] = []

    for schema in PARAM_REGISTRY:
        key = schema.param
        if key in cli_overrides:
            value = cli_overrides[key]
            val_errors = validate_value(value, schema)
            if val_errors:
                errors.extend(val_errors)
            resolved.append(ResolvedParam(
                param=key, value=value, default=schema.default,
                source="cli", schema=schema,
            ))
        elif key in toml_overrides:
            value = toml_overrides[key]
            value, coerce_err = _validate_toml_type(value, schema)
            if coerce_err:
                errors.append(coerce_err)
            val_errors = validate_value(value, schema)
            if val_errors:
                errors.extend(val_errors)
            resolved.append(ResolvedParam(
                param=key, value=value, default=schema.default,
                source="ecc.toml", schema=schema,
            ))
        else:
            resolved.append(ResolvedParam(
                param=key, value=schema.default, default=schema.default,
                source="default", schema=schema,
            ))

    return resolved, errors


# ---------------------------------------------------------------------------
# Semantic-to-backend mapping
# ---------------------------------------------------------------------------

def build_backend_overrides(resolved: list[ResolvedParam]) -> dict:
    overrides: dict = {}
    for rp in resolved:
        if rp.value == rp.default and rp.source == "default":
            continue
        maps_to = rp.schema.maps_to
        value = rp.value
        if isinstance(maps_to, str):
            overrides[maps_to] = value
        elif isinstance(maps_to, dict):
            for parent_key, child_key in maps_to.items():
                if parent_key not in overrides:
                    overrides[parent_key] = {}
                overrides[parent_key][child_key] = value
    return overrides


def parse_cli_overrides(pairs: list[str]) -> tuple[dict[str, object], list[str]]:
    result: dict[str, object] = {}
    errors: list[str] = []

    for pair in pairs:
        if "=" not in pair:
            errors.append(f"malformed override: '{pair}' (expected key=value)")
            continue

        key, _, raw_value = pair.partition("=")
        key = key.strip()
        raw_value = raw_value.strip()

        schema = lookup_schema(key)
        if schema is None:
            errors.append(f"unknown parameter: '{key}'")
            continue

        try:
            value = parse_value(raw_value, schema)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        val_errors = validate_value(value, schema)
        if val_errors:
            errors.extend(val_errors)
            continue

        result[key] = value

    return result, errors


def parse_toml_params(params_table: dict) -> tuple[dict[str, object], list[str]]:
    flat: dict[str, object] = {}
    errors: list[str] = []

    for group_key, group_val in params_table.items():
        if not isinstance(group_val, dict):
            errors.append(f"[params.{group_key}] must be a table, got {type(group_val).__name__}")
            continue

        for name_key, value in group_val.items():
            param_key = f"{group_key}.{name_key}"
            schema = lookup_schema(param_key)
            if schema is None:
                errors.append(f"unknown parameter in ecc.toml: '{param_key}'")
                continue

            try:
                if isinstance(value, str):
                    parsed = parse_value(value, schema)
                else:
                    parsed, type_err = _validate_toml_type(value, schema)
                    if type_err:
                        errors.append(type_err)
                        continue
            except ValueError as exc:
                errors.append(str(exc))
                continue

            val_errors = validate_value(parsed, schema)
            if val_errors:
                errors.extend(val_errors)
                continue

            flat[param_key] = parsed

    return flat, errors
