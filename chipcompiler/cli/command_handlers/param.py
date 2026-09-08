import os

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project import toml_edit
from chipcompiler.cli.project.params import (
    lookup_schema,
    parse_value,
    resolve_parameters,
    validate_pdk_target,
    validate_value,
)


def _manifest_mode_error(ctx: CommandContext) -> CommandResult | None:
    """ecc param operates on ecc.toml; manifest projects have none (yet)."""
    if ctx.config is None and ctx.project_state == "manifest":
        return CommandResult.err(
            [
                error_record(
                    "param_requires_ecc_toml",
                    reason="ecc param requires ecc.toml; project.json projects not supported yet",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                )
            ]
        )
    return None


def param_list(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_list(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err(
            [error_record("invalid_param_config", reason=e) for e in param_errors]
        )
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)
    project = ctx.project

    selected_step = (getattr(args, "step", None) or "").casefold()
    show_all = bool(getattr(args, "all", False))
    records = []
    for rp in resolved:
        s = rp.schema
        if selected_step and selected_step not in {s.group.casefold(), s.applies.casefold()}:
            continue
        if not selected_step and not show_all and s.has_direct_target and not rp.is_explicit:
            continue
        record = {
            "param": s.param,
            "group": s.group,
            "name": s.name,
            "value": rp.value,
            "default": s.default,
            "source": rp.source,
            "type": s.type,
            "applies": s.applies,
            "maps_to": _maps_to_str(s.maps_to),
            "description": s.description,
            "inspect": disclosure_cmd(f"ecc param show {s.param}", project),
        }
        if s.config_target is not None:
            record["config_target"] = _config_target_str(s.config_target)
        if s.pdk_target is not None:
            record["pdk_target"] = _pdk_target_str(s.pdk_target)
        if s.range is not None:
            record["range"] = f"[{s.range[0]}, {s.range[1]}]"
        if s.choices is not None:
            record["choices"] = ", ".join(s.choices)
        if s.unit is not None:
            record["unit"] = s.unit
        records.append(record)

    return CommandResult.ok(records)


def param_show(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_show(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    key = args.key
    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err(
            [
                error_record(
                    "unknown_parameter",
                    param=key,
                )
            ],
            exit_code=1,
        )

    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err(
            [error_record("invalid_param_config", reason=e) for e in param_errors]
        )
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)
    rp = next(r for r in resolved if r.param == key)

    record = {
        "param": rp.param,
        "value": rp.value,
        "default": rp.default,
        "source": rp.source,
        "type": schema.type,
        "applies": schema.applies,
        "maps_to": _maps_to_str(schema.maps_to),
        "description": schema.description,
        "inspect": disclosure_cmd(f"ecc param show {rp.param}", ctx.project),
        "set": disclosure_cmd(f"ecc param set {rp.param}", ctx.project),
        "run": disclosure_cmd(f"ecc run --set {rp.param}=<value>", ctx.project),
    }
    if schema.config_target is not None:
        record["config_target"] = _config_target_str(schema.config_target)
    if schema.pdk_target is not None:
        record["pdk_target"] = _pdk_target_str(schema.pdk_target)
    if schema.range is not None:
        record["range"] = f"[{schema.range[0]}, {schema.range[1]}]"
    if schema.choices is not None:
        record["choices"] = ", ".join(schema.choices)
    if schema.unit is not None:
        record["unit"] = schema.unit

    return CommandResult.ok([record])


def param_set(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_set(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    key = args.key
    raw_value = args.value

    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err(
            [
                error_record(
                    "unknown_parameter",
                    param=key,
                )
            ],
            exit_code=1,
        )

    try:
        value = parse_value(raw_value, schema)
    except ValueError as exc:
        return CommandResult.err(
            [
                error_record(
                    "invalid_value",
                    param=key,
                    reason=str(exc),
                )
            ],
            exit_code=1,
        )

    val_errors = validate_value(value, schema)
    if val_errors:
        return CommandResult.err(
            [
                error_record(
                    "invalid_value",
                    param=key,
                    reason=val_errors[0],
                )
            ],
            exit_code=1,
        )

    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                )
            ],
            exit_code=1,
        )

    if schema.pdk_target is not None:
        from chipcompiler.cli.project.config import load_project_config

        problem = validate_pdk_target(schema, value, load_project_config(config_path))
        if problem is not None:
            return CommandResult.err(
                [error_record("invalid_value", param=key, reason=problem)], exit_code=1
            )

    _write_param_to_toml(config_path, schema, value)

    return CommandResult.ok(
        [
            {
                "param": key,
                "value": value,
                "status": "set",
                "source": "ecc.toml",
            }
        ]
    )


def param_unset(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_unset(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    key = args.key

    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err(
            [
                error_record(
                    "unknown_parameter",
                    param=key,
                )
            ],
            exit_code=1,
        )

    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.ok(
            [
                {
                    "param": key,
                    "status": "no_override",
                    "source": "default",
                }
            ]
        )

    removed = _remove_param_from_toml(config_path, schema)

    if removed:
        return CommandResult.ok(
            [
                {
                    "param": key,
                    "status": "unset",
                    "value": schema.default,
                    "source": "default",
                }
            ]
        )
    return CommandResult.ok(
        [
            {
                "param": key,
                "status": "no_override",
                "source": "default",
            }
        ]
    )


def param_diff(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_diff(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err(
            [error_record("invalid_param_config", reason=e) for e in param_errors]
        )
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)

    records = []
    for rp in resolved:
        if rp.value != rp.default:
            records.append(
                {
                    "param": rp.param,
                    "value": rp.value,
                    "default": rp.default,
                    "source": rp.source,
                }
            )

    if not records:
        return CommandResult.ok([{"diff_status": "clean"}])

    return CommandResult.ok(records)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _maps_to_str(maps_to):
    if maps_to is None:
        return ""
    if isinstance(maps_to, str):
        return maps_to
    parts = [f"{k}.{v}" for k, v in maps_to.items()]
    return ", ".join(parts)


def _config_target_str(target) -> str:
    return f"{target.config_key}:{'.'.join(target.json_path)}"


def _pdk_target_str(target: str) -> str:
    return f"pdk.overrides:{target}"


def _find_config_path(project_dir: str) -> str | None:
    path = os.path.join(project_dir, "ecc.toml")
    return path if os.path.isfile(path) else None


def _load_toml_overrides(project_dir: str) -> tuple[dict[str, object], list[str]]:
    from chipcompiler.cli.project.config import load_project_config

    config_path = _find_config_path(project_dir)
    if config_path is None:
        return {}, []

    cfg = load_project_config(config_path)
    errors = list(getattr(cfg, "_param_errors", []))
    toml_error = getattr(cfg, "_toml_error", None)
    if toml_error:
        errors.insert(0, f"malformed ecc.toml: {toml_error}")
    overrides = dict(cfg.params_overrides)
    for pdk_key, value in cfg.pdk_overrides.items():
        schema = lookup_schema(f"pdk.{pdk_key}")
        if schema is not None and schema.pdk_target == pdk_key:
            overrides[schema.param] = value
    if "design.frequency_mhz" not in overrides and cfg.design_frequency_mhz > 0:
        overrides["design.frequency_mhz"] = cfg.design_frequency_mhz
    return overrides, errors


# TODO: Move ecc.toml parameter editing into chipcompiler.data.project_config_edit
# or the future EccTomlConfig owner. CLI should only call the edit operation and
# translate its result into command records.
def _write_param_to_toml(config_path: str, schema, value: object) -> None:
    if schema.pdk_target is not None:
        target_table, name = "pdk.overrides", schema.pdk_target
    else:
        group, _, name = schema.param.rpartition(".")
        target_table = f"params.{group}"

    with open(config_path) as f:
        original = f.read()

    new_text = toml_edit.set_scoped_key(original, target_table, name, value)

    with open(config_path, "w") as f:
        f.write(new_text)


def _remove_param_from_toml(config_path: str, schema) -> bool:
    if schema.pdk_target is not None:
        target_table, name = "pdk.overrides", schema.pdk_target
    else:
        group, _, name = schema.param.rpartition(".")
        target_table = f"params.{group}"

    with open(config_path) as f:
        original = f.read()

    result = toml_edit.remove_scoped_key(original, target_table, name)
    if result is None:
        return False

    with open(config_path, "w") as f:
        f.write(result)
    return True
