"""Canonical public parameter catalog and schema operations.

The catalog is shared by the headless Engine, CLI, and Studio adapter. CLI
specific PDK path validation remains in ``chipcompiler.cli.project.params``.
"""

import json
from copy import deepcopy
from dataclasses import dataclass

from chipcompiler.data.config_params import CONFIG_PARAM_SCHEMAS
from chipcompiler.data.config_params.common import ConfigTarget, ParamSchema, PdkVariant
from chipcompiler.data.config_params.macro import SCHEMAS as MACRO_SCHEMAS
from chipcompiler.data.config_params.sdc import SCHEMAS as SDC_SCHEMAS
from chipcompiler.data.step_parameters import STEP_TABLE, is_step_scoped, parse_step_key, step_key

_SEMANTIC_PARAM_REGISTRY: tuple[ParamSchema, ...] = (
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
        "pre_floorplan",
        "Core utilization ratio",
        {"core": "utilitization"},
        range=(0.01, 1.0),
        example="0.45",
        config_target=ConfigTarget("floorplan", ("die_builder", "die_util", "utilization")),
        pdk_variants={"sg13g2": PdkVariant(0.65)},
    ),
    ParamSchema(
        "floorplan.core_margin",
        "floorplan",
        "core_margin",
        "list[float]",
        [2, 2],
        "pre_floorplan",
        "Core margin in micrometers [horizontal, vertical]",
        {"core": "margin"},
        example="[2, 2]",
        pdk_variants={"sg13g2": PdkVariant([17.5, 17.5])},
        config_target=ConfigTarget(
            "floorplan", ("die_builder", "margin", "left_micron"), element=0
        ),
        extra_config_targets=(
            ConfigTarget("floorplan", ("die_builder", "margin", "right_micron"), element=0),
            ConfigTarget("floorplan", ("die_builder", "margin", "top_micron"), element=1),
            ConfigTarget("floorplan", ("die_builder", "margin", "bottom_micron"), element=1),
        ),
    ),
    ParamSchema(
        "floorplan.aspect_ratio",
        "floorplan",
        "aspect_ratio",
        "float",
        1.0,
        "pre_floorplan",
        "Core aspect ratio (width/height)",
        {"core": "aspect_ratio"},
        range=(0.1, 10.0),
        example="1.0",
        config_target=ConfigTarget("floorplan", ("die_builder", "die_util", "aspect_ratio")),
    ),
    ParamSchema(
        "cts.max_fanout",
        "cts",
        "max_fanout",
        "int",
        32,
        "cts",
        "Maximum fanout for clock tree synthesis",
        range=(1, 200),
        example="16",
        config_target=ConfigTarget("cts", ("max_fanout",)),
        fork=True,
    ),
    ParamSchema(
        "place.target_density",
        "place",
        "target_density",
        "float",
        0.4,
        "placement",
        "Target placement density",
        range=(0.1, 1.0),
        example="0.65",
        config_target=ConfigTarget("dreamplace", ("target_density",)),
        pdk_variants={"sg13g2": PdkVariant(0.65)},
        fork=True,
    ),
    ParamSchema(
        "place.cell_padding_x",
        "place",
        "cell_padding_x",
        "int",
        200,
        "placement",
        "Cell padding in x-direction in database units",
        range=(0, 10000),
        example="400",
        config_target=ConfigTarget("dreamplace", ("cell_padding_x",)),
        pdk_variants={"sg13g2": PdkVariant(0)},
        fork=True,
    ),
    ParamSchema(
        "route.bottom_layer",
        "route",
        "bottom_layer",
        "str",
        "MET2",
        "placement,routing",
        "Bottom routing layer",
        choices=("MET1", "MET2", "MET3", "MET4", "MET5"),
        example="MET2",
        config_target=ConfigTarget("routing", ("RT", "-bottom_routing_layer")),
        extra_config_targets=(
            ConfigTarget("db", ("LayerSettings", "routing_layer_1st")),
            ConfigTarget("dreamplace", ("gpugr_bottom_routing_layer",)),
        ),
        pdk_variants={
            "sg13g2": PdkVariant("Metal2", ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5"))
        },
        fork=True,
    ),
    ParamSchema(
        "route.top_layer",
        "route",
        "top_layer",
        "str",
        "MET5",
        "placement,routing",
        "Top routing layer",
        choices=("MET2", "MET3", "MET4", "MET5", "MET6"),
        example="MET5",
        config_target=ConfigTarget("routing", ("RT", "-top_routing_layer")),
        extra_config_targets=(ConfigTarget("dreamplace", ("gpugr_top_routing_layer",)),),
        pdk_variants={"sg13g2": PdkVariant("Metal5", ("Metal2", "Metal3", "Metal4", "Metal5"))},
        fork=True,
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
    ParamSchema(
        param="geometry.clock_tree",
        group="geometry",
        name="clock_tree",
        type="bool",
        default=False,
        applies="all",
        description=(
            "Generate clock-tree visualization data for post_floorplan, CTS, and filler; "
            "filler uses TYPICAL RC when available"
        ),
        maps_to={"geometry": "clock_tree"},
        example="true",
        output_only=True,
    ),
)

_REPLAY_SCHEMA = ParamSchema(
    param="replay.enabled",
    group="replay",
    name="enabled",
    type="bool",
    default=False,
    applies="all",
    description="Capture offline layout Replay data for supported steps on the next execution",
    maps_to={"replay": "enabled"},
    example="true",
    output_only=True,
)

PARAM_REGISTRY = (
    _SEMANTIC_PARAM_REGISTRY
    + CONFIG_PARAM_SCHEMAS
    + MACRO_SCHEMAS
    + SDC_SCHEMAS
    + (_REPLAY_SCHEMA,)
)
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
        if field != "default" and getattr(schema, field, None) in (None, "")
    ]


def validate_schema_type(value: object, schema: ParamSchema) -> tuple[object, str | None]:
    # An unset default is also valid in exported, resolved workspace parameters.
    if value is None and schema.default is None:
        return None, None
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


def validate_value(value: object, schema: ParamSchema, pdk: str | None = None) -> list[str]:
    if value is None and schema.default is None:
        return []
    errors = []
    if schema.range is not None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"value {value!r} is not numeric for {schema.param}")
        elif value < schema.range[0] or (schema.range[1] is not None and value > schema.range[1]):
            errors.append(
                f"value {value} out of range [{schema.range[0]}, {schema.range[1]}] "
                f"for {schema.param}"
            )
    choices = schema.choices_for(pdk)
    if choices is not None and str(value) not in choices:
        errors.append(f"value '{value}' not in allowed choices {choices} for {schema.param}")
    return errors


@dataclass
class ResolvedParam:
    param: str
    value: object
    default: object
    source: str
    schema: ParamSchema
    #: The step of a step-scoped (DreamPlace) value; ``None`` for the parameter itself.
    step: str | None = None

    @property
    def is_explicit(self) -> bool:
        return self.source != "default"

    @property
    def key(self) -> str:
        """The override key: ``<step>:<param>`` for a step value, else the parameter."""
        return self.param if self.step is None else step_key(self.step, self.param)


def resolve_parameters(
    toml_overrides=None, cli_overrides=None, manifest_overrides=None, pdk: str | None = None
):
    layers = (
        (cli_overrides or {}, "cli"),
        (toml_overrides or {}, "ecc.toml"),
        (manifest_overrides or {}, "project.json"),
    )
    resolved, errors = [], []
    for schema in PARAM_REGISTRY:
        default = schema.default_for(pdk)
        found = _resolve_key(schema.param, schema, layers, pdk, errors)
        value, source = found if found is not None else (default, "default")
        resolved.append(ResolvedParam(schema.param, value, default, source, schema))
        # A step-scoped parameter also resolves each step value a layer sets.
        for step in schema.steps if is_step_scoped(schema) else ():
            found = _resolve_key(step_key(step, schema.param), schema, layers, pdk, errors)
            if found is not None:
                value, source = found
                resolved.append(ResolvedParam(schema.param, value, default, source, schema, step))
    return resolved, errors


def _resolve_key(key, schema, layers, pdk, errors):
    """``(value, source)`` of *key* from the highest layer setting it, or ``None``."""
    for layer, source in layers:
        if key not in layer:
            continue
        value = layer[key]
        if source != "cli":
            value, type_error = validate_schema_type(value, schema)
            if type_error:
                errors.append(type_error)
        errors.extend(validate_value(value, schema, pdk))
        return value, source
    return None


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
    """The workspace config patch of the explicit *resolved* values.

    Step-scoped (DreamPlace) values never patch the workspace baseline: each
    step replays its own values (:func:`config_patch` in ``step_config_patch``).
    """
    return config_patch(item for item in resolved if not is_step_scoped(item.schema))


def config_patch(resolved):
    """``{config_key: {json path...}}`` of the explicit direct-config *resolved* values."""
    overrides = {}
    for item in resolved:
        # Parameters stored in the workspace payload (maps_to) are derived from
        # it at refresh; only direct config parameters carry a replay patch.
        if not item.is_explicit or item.schema.maps_to is not None:
            continue
        for target in item.schema.config_targets:
            current = overrides.setdefault(target.config_key, {})
            for key in target.json_path[:-1]:
                current = current.setdefault(key, {})
            current[target.json_path[-1]] = target.render(item.value)
    return overrides


def build_step_params(resolved) -> dict[str, dict[str, object]]:
    """The ``step_params`` payload (``{step: {param: value}}``) of the resolved step values."""
    values: dict[str, dict[str, object]] = {}
    for item in resolved:
        if item.step is not None:
            values.setdefault(item.step, {})[item.param] = deepcopy(item.value)
    return values


def build_pdk_overrides(resolved):
    return {
        item.schema.pdk_target: item.value
        for item in resolved
        if item.schema.pdk_target and item.is_explicit
    }


def parse_cli_overrides(pairs, pdk: str | None = None):
    result, errors = {}, []
    for pair in pairs:
        if "=" not in pair:
            errors.append(f"malformed override: '{pair}' (expected key=value)")
            continue
        key, raw = (part.strip() for part in pair.split("=", 1))
        step, schema, key_error = parse_step_key(key)
        if key_error is not None:
            errors.append(key_error)
            continue
        assert schema is not None  # an unknown parameter is a key error
        # Store the spelling ``resolve_parameters`` looks up (``placement:place.x``).
        key = schema.param if step is None else step_key(step, schema.param)
        try:
            value = parse_value(raw, schema)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        value_errors = validate_value(value, schema, pdk)
        if value_errors:
            errors.extend(value_errors)
            continue
        result[key] = value
    return result, errors


def parse_toml_params(params_table, pdk: str | None = None):
    flat, errors = {}, []

    def visit(path, value, step=None):
        key = ".".join(path)
        schema = lookup_schema(key)
        if schema:
            if step is not None:
                key = step_key(step, key)
            _step, _schema, key_error = parse_step_key(key)
            if key_error is not None:
                errors.append(f"{key_error} (ecc.toml)")
                return
            try:
                parsed = parse_value(value, schema) if isinstance(value, str) else value
                parsed, type_error = validate_schema_type(parsed, schema)
                if type_error:
                    errors.append(type_error)
                    return
            except ValueError as exc:
                errors.append(str(exc))
                return
            value_errors = validate_value(parsed, schema, pdk)
            if value_errors:
                errors.extend(value_errors)
                return
            flat[key] = parsed
            return
        if isinstance(value, dict):
            for child, child_value in value.items():
                visit((*path, child), child_value, step)
        else:
            errors.append(f"unknown parameter in ecc.toml: '{key}'")

    for group, value in params_table.items():
        if group == STEP_TABLE and isinstance(value, dict):
            # [params.step.<step>.<group>] holds step-scoped (DreamPlace) values.
            for step, table in value.items():
                if not isinstance(table, dict):
                    errors.append(f"[params.step.{step}] must be a table")
                    continue
                for child, child_value in table.items():
                    visit((child,), child_value, step)
        elif isinstance(value, dict):
            visit((group,), value)
        else:
            errors.append(f"[params.{group}] must be a table, got {type(value).__name__}")
    return flat, errors
