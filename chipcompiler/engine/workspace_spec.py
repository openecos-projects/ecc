from copy import deepcopy
from pathlib import Path
from typing import Any

from chipcompiler.cli.project.params import list_schemas, resolve_parameters
from chipcompiler.engine.pdk_binding import pdk_binding_content_hash
from chipcompiler.rtl2gds import get_flow_builders, normalize_flow_step
from chipcompiler.utility.filelist import validate_filelist

SCHEMA_VERSION = 1
_INPUT_ROLES = frozenset({"rtl", "filelist", "netlist", "goldenNetlist", "def", "sdc", "spef"})
_PDK_FILE_ROLES = frozenset({"tech", "lef", "liberty", "mapping"})
_SPEC_FIELDS = frozenset(
    {"schemaVersion", "design", "inputMode", "inputs", "pdk", "flow", "mpc", "parameters"}
)


def describe_workspace_spec() -> dict[str, Any]:
    flows = []
    for flow_id, builder in sorted(get_flow_builders().items()):
        steps = [_enum_value(step) for step, _tool, _state in builder()]
        flows.append({"flowId": flow_id, "stepIds": steps})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "parameterCatalog": [
            {
                "id": schema.param,
                "type": schema.type,
                "default": deepcopy(schema.default),
                "appliesTo": schema.applies,
                "backendMapping": deepcopy(schema.maps_to),
                **({"range": list(schema.range)} if schema.range else {}),
                **({"choices": list(schema.choices)} if schema.choices else {}),
                **({"unit": schema.unit} if schema.unit else {}),
            }
            for schema in list_schemas()
        ],
        "flowDefinitions": flows,
        "inputRoleRules": {
            "roles": sorted(_INPUT_ROLES),
            "rtl": {"rtl": "oneOrMore", "filelist": "exactlyOneAlternative"},
            "postSynthesis": {"netlist": "exactlyOne"},
            "manualPdk": {
                "tech": "exactlyOne",
                "lef": "oneOrMore",
                "liberty": "oneOrMore",
                "mapping": "zeroOrOne",
            },
        },
    }


def validate_workspace_spec(spec: object, bindings: object) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not isinstance(spec, dict):
        return {"issues": [_issue("invalid_type", "", expected="object")]}
    spec = {str(key): value for key, value in spec.items()}
    if not isinstance(bindings, dict):
        bindings = {}
        issues.append(_issue("invalid_type", "/bindings", expected="object"))
    else:
        bindings = {str(key): value for key, value in bindings.items()}

    _unknown_fields(spec, _SPEC_FIELDS, "", issues)
    if spec.get("schemaVersion") != SCHEMA_VERSION or isinstance(spec.get("schemaVersion"), bool):
        issues.append(
            _issue(
                "unsupported_schema_version",
                "/schemaVersion",
                supported=SCHEMA_VERSION,
            )
        )

    design = _mapping(spec.get("design"), "/design", issues)
    _unknown_fields(design, {"name", "topModule", "clockPort"}, "/design", issues)
    _required_string(design, "name", "/design/name", issues)
    _required_string(design, "topModule", "/design/topModule", issues)
    if "clockPort" in design and not _nonempty_string(design["clockPort"]):
        issues.append(_issue("invalid_value", "/design/clockPort"))

    input_mode = spec.get("inputMode")
    if input_mode not in {"rtl", "postSynthesis"}:
        issues.append(_issue("invalid_input_mode", "/inputMode"))
    inputs = _refs(spec.get("inputs"), "inputId", _INPUT_ROLES, "/inputs", issues)
    input_bindings = _input_bindings(bindings.get("inputs"), issues)
    _validate_binding_set(inputs, input_bindings, issues)
    _validate_input_roles(input_mode, inputs, issues)
    _validate_input_files(inputs, input_bindings, issues)

    pdk = _mapping(spec.get("pdk"), "/pdk", issues)
    _unknown_fields(pdk, {"familyId", "version", "mode", "files", "overrides"}, "/pdk", issues)
    _required_string(pdk, "familyId", "/pdk/familyId", issues)
    mode = pdk.get("mode")
    if mode not in {"default", "manual"}:
        issues.append(_issue("invalid_pdk_mode", "/pdk/mode"))
    overrides = pdk.get("overrides", {})
    if not isinstance(overrides, dict):
        issues.append(_issue("invalid_type", "/pdk/overrides", expected="object"))
    else:
        _unknown_fields(overrides, {"dont_use", "abc_load"}, "/pdk/overrides", issues)
        if "dont_use" in overrides and not (
            isinstance(overrides["dont_use"], list)
            and all(isinstance(value, str) for value in overrides["dont_use"])
        ):
            issues.append(_issue("invalid_type", "/pdk/overrides/dont_use", expected="array"))
        if "abc_load" in overrides and (
            isinstance(overrides["abc_load"], bool)
            or not isinstance(overrides["abc_load"], (int, float))
        ):
            issues.append(_issue("invalid_type", "/pdk/overrides/abc_load", expected="number"))
    pdk_bindings = _mapping(bindings.get("pdk"), "/bindings/pdk", issues)
    root = pdk_bindings.get("root")
    if not isinstance(root, str) or not root.strip() or not Path(root).is_dir():
        issues.append(_issue("pdk_binding_missing", "/bindings/pdk/root"))
    _validate_pdk_files(pdk, pdk_bindings, issues)
    requested_version = pdk.get("version")
    bound_version = pdk_bindings.get("version")
    if requested_version and bound_version and requested_version != bound_version:
        issues.append(
            _issue(
                "pdk_binding_mismatch",
                "/bindings/pdk/version",
                expected=requested_version,
                actual=bound_version,
            )
        )

    flow = _mapping(spec.get("flow"), "/flow", issues)
    _unknown_fields(flow, {"flowId", "fromStepId", "throughStepId"}, "/flow", issues)
    flow_steps = _validate_flow(flow, issues)

    parameters = spec.get("parameters", {})
    if not isinstance(parameters, dict):
        issues.append(_issue("invalid_type", "/parameters", expected="object"))
        parameters = {}
    else:
        parameters = {str(key): value for key, value in parameters.items()}
    known_parameters = {schema.param for schema in list_schemas()}
    for parameter_id in parameters:
        if parameter_id not in known_parameters:
            issues.append(_issue("unknown_parameter", f"/parameters/{_pointer(parameter_id)}"))
    resolved_parameters, parameter_errors = resolve_parameters(
        toml_overrides={key: value for key, value in parameters.items() if key in known_parameters}
    )
    for error in parameter_errors:
        parameter_id = next((key for key in parameters if key in error), "")
        issues.append(
            _issue(
                "invalid_parameter",
                f"/parameters/{_pointer(parameter_id)}" if parameter_id else "/parameters",
                reason=error,
            )
        )
    _validate_parameter_applicability(parameters, flow_steps, issues)

    mpc = spec.get("mpc")
    if mpc is not None:
        mpc = _mapping(mpc, "/mpc", issues)
        _unknown_fields(mpc, {"resourceId", "version", "designId"}, "/mpc", issues)
        for key in ("resourceId", "version", "designId"):
            _required_string(mpc, key, f"/mpc/{key}", issues)
        mpc_binding = _mapping(bindings.get("mpc"), "/bindings/mpc", issues)
        if not isinstance(mpc_binding.get("template"), dict):
            issues.append(_issue("mpc_binding_missing", "/bindings/mpc/template"))

    if any(issue["severity"] == "error" for issue in issues):
        return {"issues": issues}

    resolved = deepcopy(spec)
    resolved["parameters"] = _effective_parameter_values(resolved_parameters, flow_steps)
    resolved["pdk"] = {
        **deepcopy(pdk),
        "version": requested_version or bound_version or "unversioned",
        "contentHash": pdk_binding_content_hash(pdk, pdk_bindings),
    }
    return {"resolvedWorkspaceSpec": resolved, "issues": issues}


def _validate_input_roles(
    input_mode: object,
    inputs: list[dict[str, str]],
    issues: list[dict[str, Any]],
) -> None:
    roles = [item["role"] for item in inputs]
    if input_mode == "rtl":
        if ("rtl" in roles) == ("filelist" in roles):
            issues.append(_issue("conflicting_input_roles", "/inputs"))
        if roles.count("filelist") > 1:
            issues.append(_issue("filelist_cardinality", "/inputs"))
        if "netlist" in roles:
            issues.append(_issue("input_role_not_allowed", "/inputs", mode="rtl"))
    elif input_mode == "postSynthesis":
        if roles.count("netlist") != 1:
            issues.append(_issue("netlist_cardinality", "/inputs"))
        if any(role in {"rtl", "filelist"} for role in roles):
            issues.append(_issue("input_role_not_allowed", "/inputs", mode="postSynthesis"))
    for role in ("netlist", "goldenNetlist", "def", "sdc", "spef"):
        if roles.count(role) > 1:
            issues.append(_issue(f"{role}_cardinality", "/inputs"))


def _validate_input_files(
    refs: list[dict[str, str]],
    bindings: dict[str, str],
    issues: list[dict[str, Any]],
) -> None:
    for ref in refs:
        input_id = ref["inputId"]
        path = bindings.get(input_id)
        if not path:
            continue
        source = Path(path)
        pointer = f"/bindings/inputs/{_pointer(input_id)}"
        if not source.is_file():
            issues.append(_issue("input_unreadable", pointer))
            continue
        if ref["role"] != "filelist":
            continue
        try:
            _existing, missing = validate_filelist(str(source))
        except (OSError, ValueError) as exc:
            issues.append(_issue("filelist_invalid", pointer, reason=str(exc)))
            continue
        if missing:
            issues.append(_issue("filelist_source_missing", pointer, missing=missing))


def _validate_binding_set(
    refs: list[dict[str, str]],
    bindings: dict[str, str],
    issues: list[dict[str, Any]],
) -> None:
    ref_ids = {item["inputId"] for item in refs}
    for input_id in sorted(ref_ids - bindings.keys()):
        issues.append(_issue("input_binding_missing", f"/bindings/inputs/{_pointer(input_id)}"))
    for input_id in sorted(bindings.keys() - ref_ids):
        issues.append(_issue("unknown_input_binding", f"/bindings/inputs/{_pointer(input_id)}"))


def _validate_pdk_files(
    pdk: dict[str, Any],
    bindings: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    mode = pdk.get("mode")
    refs = _refs(pdk.get("files", []), "fileId", _PDK_FILE_ROLES, "/pdk/files", issues)
    roles = [item["role"] for item in refs]
    rules = (
        (
            ("tech", roles.count("tech") == 1),
            ("lef", roles.count("lef") >= 1),
            ("liberty", roles.count("liberty") >= 1),
            ("mapping", roles.count("mapping") <= 1),
        )
        if mode == "manual"
        else (
            ("tech", roles.count("tech") <= 1),
            ("mapping", roles.count("mapping") <= 1),
        )
    )
    for role, valid in rules:
        if not valid:
            issues.append(_issue(f"pdk_{role}_cardinality", "/pdk/files"))
    raw_file_bindings = bindings.get("files", {})
    file_bindings = raw_file_bindings if isinstance(raw_file_bindings, dict) else {}
    ref_ids = {item["fileId"] for item in refs}
    for file_id in sorted(ref_ids - file_bindings.keys()):
        issues.append(
            _issue("pdk_file_binding_missing", f"/bindings/pdk/files/{_pointer(file_id)}")
        )
    for file_id in sorted(file_bindings.keys() - ref_ids):
        issues.append(
            _issue("unknown_pdk_file_binding", f"/bindings/pdk/files/{_pointer(file_id)}")
        )
    for file_id, path in file_bindings.items():
        if file_id in ref_ids and (not isinstance(path, str) or not Path(path).is_file()):
            issues.append(_issue("pdk_file_unreadable", f"/bindings/pdk/files/{_pointer(file_id)}"))


def _validate_flow(flow: dict[str, Any], issues: list[dict[str, Any]]) -> set[str]:
    flow_id = flow.get("flowId")
    builder = get_flow_builders().get(flow_id) if isinstance(flow_id, str) else None
    if builder is None:
        issues.append(_issue("unknown_flow", "/flow/flowId"))
        return set()
    steps = [_enum_value(step) for step, _tool, _state in builder()]
    start = flow.get("fromStepId")
    end = flow.get("throughStepId")
    if (start is None) != (end is None):
        issues.append(_issue("flow_boundaries_incomplete", "/flow"))
        return set(steps)
    if start is None:
        return set(steps)
    if start not in steps:
        issues.append(_issue("unknown_flow_boundary", "/flow/fromStepId"))
    if end not in steps:
        issues.append(_issue("unknown_flow_boundary", "/flow/throughStepId"))
    if start in steps and end in steps:
        start_index, end_index = steps.index(start), steps.index(end)
        if start_index > end_index:
            issues.append(_issue("flow_boundary_reversed", "/flow"))
        else:
            return set(steps[start_index : end_index + 1])
    return set()


def _validate_parameter_applicability(
    explicit: dict[str, Any],
    flow_steps: set[str],
    issues: list[dict[str, Any]],
) -> None:
    normalized_steps = {step.lower() for step in flow_steps}
    aliases = {
        "synthesis": "synth",
        "floorplan": "floor",
        "fixfanout": "fanout",
        "placement": "place",
        "routing": "route",
    }
    normalized_steps |= {aliases.get(step, step) for step in normalized_steps}
    for schema in list_schemas():
        if schema.param not in explicit:
            continue
        if schema.applies == "all":
            continue
        applies = aliases.get(schema.applies.lower(), schema.applies.lower())
        if flow_steps and applies not in normalized_steps:
            issues.append(
                _issue(
                    "inapplicable_parameter",
                    f"/parameters/{_pointer(schema.param)}",
                    appliesTo=schema.applies,
                )
            )


def _effective_parameter_values(resolved, steps: set[str]) -> dict[str, object]:
    available = {normalize_flow_step(step).casefold() for step in steps}
    return {
        parameter.param: deepcopy(parameter.value)
        for parameter in resolved
        if parameter.schema.pdk_target is None
        and (
            parameter.schema.applies == "all"
            or normalize_flow_step(parameter.schema.applies).casefold() in available
        )
    }


def _refs(
    value: object,
    id_key: str,
    roles: frozenset[str],
    path: str,
    issues: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        issues.append(_issue("invalid_type", path, expected="array"))
        return []
    refs = []
    seen = set()
    for index, value_item in enumerate(value):
        item_path = f"{path}/{index}"
        if not isinstance(value_item, dict):
            issues.append(_issue("invalid_type", item_path, expected="object"))
            continue
        item = {str(key): field for key, field in value_item.items()}
        _unknown_fields(item, {id_key, "role"}, item_path, issues)
        item_id = item.get(id_key)
        role = item.get("role")
        if not _nonempty_string(item_id):
            issues.append(_issue("invalid_value", f"{item_path}/{id_key}"))
            continue
        if item_id in seen:
            issues.append(_issue("duplicate_ref", f"{item_path}/{id_key}"))
            continue
        seen.add(item_id)
        if role not in roles:
            issues.append(_issue("unknown_role", f"{item_path}/role"))
            continue
        refs.append({id_key: item_id, "role": role})
    return refs


def _input_bindings(value: object, issues: list[dict[str, Any]]) -> dict[str, str]:
    if not isinstance(value, dict):
        issues.append(_issue("invalid_type", "/bindings/inputs", expected="object"))
        return {}
    return {
        key: path for key, path in value.items() if isinstance(key, str) and isinstance(path, str)
    }


def _mapping(value: object, path: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(_issue("invalid_type", path, expected="object"))
        return {}
    return {str(key): item for key, item in value.items()}


def _unknown_fields(
    value: dict[str, Any],
    allowed: set[str] | frozenset[str],
    path: str,
    issues: list[dict[str, Any]],
) -> None:
    for key in value.keys() - allowed:
        issues.append(_issue("unknown_field", f"{path}/{_pointer(key)}"))


def _required_string(
    value: dict[str, Any], key: str, path: str, issues: list[dict[str, Any]]
) -> None:
    if not _nonempty_string(value.get(key)):
        issues.append(_issue("required", path))


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _issue(code: str, path: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "path": path, "severity": "error", "details": details}
