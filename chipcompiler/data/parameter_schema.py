"""Canonical public parameter catalog and schema operations.

The catalog is shared by the headless Engine, CLI, and Studio adapter. CLI
specific PDK path validation remains in ``chipcompiler.cli.project.params``.
"""

import copy
import json
from dataclasses import dataclass

from chipcompiler.data.config_params import CONFIG_PARAM_SCHEMAS
from chipcompiler.data.config_params.common import ParamSchema

_LEGACY_PARAM_REGISTRY: tuple[ParamSchema, ...] = (
    ParamSchema(
        "design.frequency_mhz",
        "design",
        "frequency_mhz",
        "float",
        100.0,
        "synthesis",
        "Target clock frequency in MHz",
        "frequency_max",
        range=(1e-6, 10000.0),
        unit="MHz",
        example="200.0",
    ),
    ParamSchema(
        "floorplan.core_util",
        "floorplan",
        "core_util",
        "float",
        0.4,
        "floorplan",
        "Core utilization ratio",
        {"core": "utilitization"},
        range=(0.01, 1.0),
        example="0.45",
    ),
    ParamSchema(
        "floorplan.core_margin",
        "floorplan",
        "core_margin",
        "list[int]",
        [2, 2],
        "floorplan",
        "Core margin in micrometers [horizontal, vertical]",
        {"core": "margin"},
        example="[2, 2]",
    ),
    ParamSchema(
        "floorplan.aspect_ratio",
        "floorplan",
        "aspect_ratio",
        "float",
        1.0,
        "floorplan",
        "Core aspect ratio (width/height)",
        {"core": "aspect_ratio"},
        range=(0.1, 10.0),
        example="1.0",
    ),
    ParamSchema(
        "cts.max_fanout",
        "cts",
        "max_fanout",
        "int",
        20,
        "cts",
        "Maximum fanout for clock tree synthesis",
        "max_fanout",
        range=(1, 200),
        example="16",
    ),
    ParamSchema(
        "place.target_density",
        "place",
        "target_density",
        "float",
        0.2,
        "placement",
        "Target placement density",
        {"dreamplace": "target_density"},
        range=(0.1, 0.95),
        example="0.65",
    ),
    ParamSchema(
        "place.target_overflow",
        "place",
        "target_overflow",
        "float",
        0.1,
        "placement",
        "Target overflow for global placement",
        {"dreamplace": "stop_overflow"},
        range=(0.0, 1.0),
        example="0.08",
    ),
    ParamSchema(
        "place.global_right_padding",
        "place",
        "global_right_padding",
        "int",
        0,
        "placement",
        "Global right padding for placement sites",
        "global_right_padding",
        range=(0, 100),
        example="8",
    ),
    ParamSchema(
        "place.cell_padding_x",
        "place",
        "cell_padding_x",
        "int",
        300,
        "placement",
        "Cell padding in x-direction in database units",
        {"dreamplace": "cell_padding_x"},
        range=(0, 10000),
        example="400",
    ),
    ParamSchema(
        "place.routability_opt",
        "place",
        "routability_opt",
        "int",
        1,
        "placement",
        "Enable routability-driven placement optimization",
        {"dreamplace": "routability_opt_flag"},
        choices=("0", "1"),
        example="1",
    ),
    ParamSchema(
        "route.bottom_layer",
        "route",
        "bottom_layer",
        "str",
        "MET2",
        "routing",
        "Bottom routing layer",
        "bottom_layer",
        choices=("MET1", "MET2", "MET3", "MET4", "MET5"),
        example="MET2",
    ),
    ParamSchema(
        "route.top_layer",
        "route",
        "top_layer",
        "str",
        "MET5",
        "routing",
        "Top routing layer",
        "top_layer",
        choices=("MET2", "MET3", "MET4", "MET5", "MET6"),
        example="MET5",
    ),
    ParamSchema(
        "sta.max_paths",
        "sta",
        "max_paths",
        "int",
        1000,
        "sta",
        "Maximum number of paths in each STA timing report",
        "sta_max_paths",
        range=(1, 100000),
        example="1000",
    ),
    ParamSchema(
        param="flow.run_analysis",
        group="flow",
        name="run_analysis",
        type="bool",
        default=True,
        applies="all",
        description="Run per-step analysis (metrics, plots, checklist) after each step",
        maps_to="run_analysis",
        example="false",
    ),
)

PARAM_REGISTRY = _LEGACY_PARAM_REGISTRY + CONFIG_PARAM_SCHEMAS
_REGISTRY_INDEX = {schema.param: schema for schema in PARAM_REGISTRY}
_REQUIRED_FIELDS = ("param", "group", "name", "type", "default", "applies", "description")


def lookup_schema(key: str) -> ParamSchema | None:
    return _REGISTRY_INDEX.get(key)


def list_schemas() -> tuple[ParamSchema, ...]:
    return PARAM_REGISTRY


def list_groups() -> list[str]:
    return list(dict.fromkeys(schema.group for schema in PARAM_REGISTRY))


def is_known_key(key: str) -> bool:
    return key in _REGISTRY_INDEX


def validate_schema_record(schema: ParamSchema) -> list[str]:
    return [
        f"missing required field: {field}"
        for field in _REQUIRED_FIELDS
        if getattr(schema, field, None) is None
        or (field != "default" and getattr(schema, field) == "")
    ]


def validate_schema_type(value: object, schema: ParamSchema) -> tuple[object, str | None]:
    key, ptype = schema.param, schema.type
    if ptype == "int":
        return (
            (value, None)
            if isinstance(value, int) and not isinstance(value, bool)
            else (value, f"expected int for {key}, got {type(value).__name__}")
        )
    if ptype == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, f"expected float for {key}, got {type(value).__name__}"
        try:
            return float(value), None
        except OverflowError:
            return value, f"expected float for {key}, value too large to represent"
    if ptype == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str) and value.lower() in {"true", "1", "yes", "false", "0", "no"}:
            return value.lower() in {"true", "1", "yes"}, None
        return value, f"expected bool for {key}, got {type(value).__name__}"
    if ptype == "str":
        return (
            (value, None)
            if isinstance(value, str)
            else (value, f"expected str for {key}, got {type(value).__name__}")
        )
    if ptype.startswith("list["):
        if not isinstance(value, list):
            return value, f"expected list for {key}, got {type(value).__name__}"
        element_type = ptype[5:-1]
        for index, item in enumerate(value):
            if element_type == "str":
                valid = isinstance(item, str)
            elif element_type == "int":
                valid = isinstance(item, int) and not isinstance(item, bool)
            else:
                valid = isinstance(item, (int, float)) and not isinstance(item, bool)
            if not valid:
                return (
                    value,
                    f"expected {ptype} for {key}, element {index} is {type(item).__name__}",
                )
        if element_type == "float":
            try:
                return [float(item) for item in value], None
            except OverflowError:
                return value, f"expected list[float] for {key}, value too large to represent"
        return value, None
    if ptype == "json":
        return (
            (value, None)
            if isinstance(value, (dict, list))
            else (value, f"expected JSON object or array for {key}, got {type(value).__name__}")
        )
    return value, None


def parse_value(raw: str, schema: ParamSchema) -> object:
    if schema.type in {"int", "float"}:
        try:
            return int(raw) if schema.type == "int" else float(raw)
        except ValueError as exc:
            raise ValueError(f"expected {schema.type} for {schema.param}, got '{raw}'") from exc
    if schema.type == "bool":
        low = raw.lower()
        if low in {"true", "1", "yes"}:
            return True
        if low in {"false", "0", "no"}:
            return False
        raise ValueError(f"expected bool for {schema.param}, got '{raw}'")
    if schema.type == "str":
        return raw
    if schema.type.startswith("list["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parts = [part.strip() for part in raw.strip("[]() ").split(",") if part.strip()]
            element_type = schema.type[5:-1]
            try:
                parsed = (
                    [int(part) for part in parts]
                    if element_type == "int"
                    else [float(part) for part in parts]
                    if element_type == "float"
                    else parts
                )
            except ValueError as exc:
                raise ValueError(f"expected {schema.type} for {schema.param}, got '{raw}'") from exc
        value, error = validate_schema_type(parsed, schema)
        if error:
            raise ValueError(error)
        return value
    if schema.type == "json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"expected JSON for {schema.param}, got '{raw}'") from exc
    raise ValueError(f"unsupported type '{schema.type}' for {schema.param}")


def validate_value(value: object, schema: ParamSchema) -> list[str]:
    errors = []
    if schema.range is not None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"value {value!r} is not numeric for {schema.param}")
        elif value < schema.range[0] or value > schema.range[1]:
            errors.append(
                f"value {value} out of range [{schema.range[0]}, {schema.range[1]}] "
                f"for {schema.param}"
            )
    if schema.choices is not None and str(value) not in schema.choices:
        errors.append(f"value '{value}' not in allowed choices {schema.choices} for {schema.param}")
    return errors


@dataclass
class ResolvedParam:
    param: str
    value: object
    default: object
    source: str
    schema: ParamSchema

    @property
    def is_explicit(self) -> bool:
        return self.source != "default"


def resolve_parameters(toml_overrides=None, cli_overrides=None, manifest_overrides=None):
    layers = (
        (cli_overrides or {}, "cli"),
        (toml_overrides or {}, "ecc.toml"),
        (manifest_overrides or {}, "project.json"),
    )
    resolved, errors = [], []
    for schema in PARAM_REGISTRY:
        value, source = schema.default, "default"
        for layer, layer_source in layers:
            if schema.param not in layer:
                continue
            value, source = layer[schema.param], layer_source
            if source != "cli":
                value, type_error = validate_schema_type(value, schema)
                if type_error:
                    errors.append(type_error)
            errors.extend(validate_value(value, schema))
            break
        resolved.append(ResolvedParam(schema.param, value, schema.default, source, schema))
    return resolved, errors


def manifest_value_for(canonical: dict, maps_to) -> tuple[object, bool]:
    if isinstance(maps_to, str):
        return (canonical[maps_to], True) if maps_to in canonical else (None, False)
    if isinstance(maps_to, dict):
        for parent, child in maps_to.items():
            node = canonical.get(parent)
            if isinstance(node, dict) and child in node:
                return node[child], True
    return None, False


def coerce_manifest_parameters(canonical: dict, registry=PARAM_REGISTRY, skip_params=frozenset()):
    coerced, errors = copy.deepcopy(canonical), []
    for schema in registry:
        if schema.param in skip_params:
            continue
        value, present = manifest_value_for(coerced, schema.maps_to)
        if not present:
            continue
        value, error = validate_schema_type(value, schema)
        if error:
            errors.append(error)
            continue
        if isinstance(schema.maps_to, str):
            coerced[schema.maps_to] = value
        else:
            for parent, child in schema.maps_to.items():
                if isinstance(coerced.get(parent), dict) and child in coerced[parent]:
                    coerced[parent][child] = value
                    break
    return coerced, errors


def build_backend_overrides(resolved, *, include_defaults: bool = False):
    overrides = {}
    for item in resolved:
        if not include_defaults and item.source == "default" and item.value == item.default:
            continue
        target, value = item.schema.maps_to, item.value
        if isinstance(target, str):
            overrides[target] = value
        elif isinstance(target, dict):
            for parent, child in target.items():
                overrides.setdefault(parent, {})[child] = value
    return overrides


def build_config_overrides(resolved):
    overrides = {}
    for item in resolved:
        target = item.schema.config_target
        if target is None or not item.is_explicit:
            continue
        current = overrides.setdefault(target.config_key, {})
        for key in target.json_path[:-1]:
            current = current.setdefault(key, {})
        current[target.json_path[-1]] = item.value
    return overrides


def build_pdk_overrides(resolved):
    return {
        item.schema.pdk_target: item.value
        for item in resolved
        if item.schema.pdk_target and item.is_explicit
    }


def parse_cli_overrides(pairs):
    result, errors = {}, []
    for pair in pairs:
        if "=" not in pair:
            errors.append(f"malformed override: '{pair}' (expected key=value)")
            continue
        key, raw = (part.strip() for part in pair.split("=", 1))
        schema = lookup_schema(key)
        if schema is None:
            errors.append(f"unknown parameter: '{key}'")
            continue
        try:
            value = parse_value(raw, schema)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        value_errors = validate_value(value, schema)
        if value_errors:
            errors.extend(value_errors)
            continue
        result[key] = value
    return result, errors


def parse_toml_params(params_table):
    flat, errors = {}, []

    def visit(path, value):
        key = ".".join(path)
        schema = lookup_schema(key)
        if schema:
            try:
                parsed = parse_value(value, schema) if isinstance(value, str) else value
                parsed, type_error = validate_schema_type(parsed, schema)
                if type_error:
                    errors.append(type_error)
                    return
            except ValueError as exc:
                errors.append(str(exc))
                return
            value_errors = validate_value(parsed, schema)
            if value_errors:
                errors.extend(value_errors)
                return
            flat[key] = parsed
            return
        if isinstance(value, dict):
            for child, child_value in value.items():
                visit((*path, child), child_value)
        else:
            errors.append(f"unknown parameter in ecc.toml: '{key}'")

    for group, value in params_table.items():
        if isinstance(value, dict):
            visit((group,), value)
        else:
            errors.append(f"[params.{group}] must be a table, got {type(value).__name__}")
    return flat, errors
