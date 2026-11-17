import os

from chipcompiler.cli.command_handlers.param_step_values import (
    config_target_str,
    list_record,
    maps_to_str,
    pdk_target_str,
    step_diff_records,
    step_list_records,
    value_at_step,
)
from chipcompiler.cli.core.line_records import json_literal
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.cli.project.config import find_config_path
from chipcompiler.cli.project.param_edit import set_parameter, unset_parameter
from chipcompiler.cli.project.params import validate_pdk_target
from chipcompiler.data.step_parameters import (
    parse_step_key,
    split_step_key,
)
from chipcompiler.params import (
    display_key_for,
    knob_id_for,
    list_schemas,
    lookup_schema,
    parse_value,
    resolve_parameters,
    validate_value,
)
from chipcompiler.project.manifest import CONFIG_FILENAME
from chipcompiler.rtl2gds import get_flow_builders
from chipcompiler.utility.file import write_text_atomic


def _project_pdk(ctx: CommandContext) -> str | None:
    """The configured PDK family, which selects PDK-specific defaults and choices."""
    return getattr(ctx.config, "pdk_name", "") or None


def _manifest_mode_error(ctx: CommandContext) -> CommandResult | None:
    """ecc param operates on ecc.toml; manifest projects have none (yet)."""
    if ctx.config is None and ctx.project_state == "manifest":
        return CommandResult.err(
            [
                error_record(
                    "param_requires_ecc_toml",
                    reason="ecc param requires ecc.toml; project.json projects not supported yet",
                    path=os.path.join(ctx.project_dir, CONFIG_FILENAME),
                )
            ]
        )
    return None


def _step_key_error(key: str, step: str | None, reason: str) -> CommandResult:
    code = "parameter_step_required" if step is None else "parameter_not_applicable"
    return CommandResult.err([error_record(code, param=key, reason=reason)], exit_code=1)


def _parameter_flow_error(schema, ctx: CommandContext) -> CommandResult | None:
    preset = getattr(ctx.config, "flow_preset", "")
    builder = get_flow_builders().get(preset)
    if builder is None or schema.workspace_wide or schema.pdk_target is not None:
        return None
    if any(schema.applies_to(str(step)) for step, _tool, _state in builder()):
        return None
    return CommandResult.err(
        [error_record("parameter_not_in_flow", param=schema.param, preset=preset)],
        exit_code=1,
    )


def param_list(args, ctx: CommandContext) -> CommandResult:
    if (
        bool(getattr(args, "all", False))
        and ctx.output_mode == OutputMode.PLAIN
        and getattr(args, "workspace", None) is None
        and getattr(args, "step", None) is None
    ):
        return CommandResult.ok(_parameter_catalog_records())
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
    pdk = _project_pdk(ctx)
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides, pdk=pdk)
    selected_step = str(getattr(args, "step", None) or "")
    show_all = bool(getattr(args, "all", False))
    preset = getattr(ctx.config, "flow_preset", "")
    builder = get_flow_builders().get(preset)
    flow_step_names = (
        [str(step) for step, _tool, _state in builder()] if builder is not None else []
    )
    flow_steps = set(flow_step_names)
    first_flow_step = flow_step_names[0] if flow_step_names else ""
    if selected_step and flow_steps and selected_step not in flow_steps:
        return CommandResult.ok([])
    records = []
    for rp in resolved:
        s = rp.schema
        if flow_steps and not s.workspace_wide and not flow_steps.intersection(s.steps):
            continue
        if selected_step and not s.listed_at(selected_step, first_flow_step):
            continue
        _value, source = value_at_step(rp, toml_overrides, selected_step or None)
        if selected_step or show_all or not s.has_direct_target or source != "default":
            records.append(list_record(ctx, rp, toml_overrides, selected_step or None, pdk))
        if not selected_step:
            # Without a step, also list each step value ecc.toml sets ([params.step.<step>]).
            records.extend(step_list_records(ctx, rp, toml_overrides, pdk))

    return CommandResult.ok(records)


def _parameter_catalog_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for schema in sorted(list_schemas(), key=lambda item: item.param):
        record: dict[str, object] = {
            "record": "parameter",
            "id": schema.param,
            "type": schema.type,
            "default_literal": json_literal(schema.default),
            "applies_to": schema.applies,
            "maps_to_literal": json_literal(schema.maps_to),
        }
        display_key = display_key_for(schema.param)
        knob_id = knob_id_for(schema.param)
        if display_key is not None:
            record["display_key"] = display_key
        if knob_id is not None:
            record["knob_id"] = knob_id
        if schema.range is not None:
            record["range_literal"] = json_literal(list(schema.range))
        if schema.choices is not None:
            record["choices_literal"] = json_literal(list(schema.choices))
        if schema.unit is not None:
            record["unit"] = schema.unit
        if schema.description:
            record["description"] = schema.description
        records.append(record)
    return records


def param_show(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_show(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    key = args.key
    step, schema, key_error = parse_step_key(key)
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
    if key_error is not None:
        return _step_key_error(key, step, key_error)

    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err(
            [error_record("invalid_param_config", reason=e) for e in param_errors]
        )
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides, pdk=_project_pdk(ctx))
    rp = next(r for r in resolved if r.param == schema.param)
    value, source = value_at_step(rp, toml_overrides, step)

    record = {
        "param": key,
        "value": value,
        "default": rp.default,
        "source": source,
        "type": schema.type,
        "applies": schema.applies,
        "maps_to": maps_to_str(schema.maps_to),
        "description": schema.description,
        "inspect": disclosure_cmd(f"ecc param show {key}", ctx.project),
        "set": disclosure_cmd(f"ecc param set {key}", ctx.project),
        "run": disclosure_cmd(f"ecc run --set {key}=<value>", ctx.project),
    }
    if schema.config_target is not None:
        record["config_target"] = config_target_str(schema.config_target)
    if schema.pdk_target is not None:
        record["pdk_target"] = pdk_target_str(schema.pdk_target)
    if schema.range is not None:
        record["range"] = f"[{schema.range[0]}, {schema.range[1]}]"
    choices = schema.choices_for(_project_pdk(ctx))
    if choices is not None:
        record["choices"] = ", ".join(choices)
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

    step, schema, key_error = parse_step_key(key)
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
    if key_error is not None:
        return _step_key_error(key, step, key_error)
    flow_error = _parameter_flow_error(schema, ctx)
    if flow_error is not None:
        return flow_error

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

    val_errors = validate_value(value, schema, _project_pdk(ctx))
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

    config_path = find_config_path(ctx.project_dir)
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

        try:
            pdk_config = load_project_config(config_path)
        except (OSError, UnicodeDecodeError) as exc:
            return CommandResult.err(
                [error_record("config_error", param=key, reason=str(exc))], exit_code=1
            )
        problem = validate_pdk_target(schema, value, pdk_config)
        if problem is not None:
            return CommandResult.err(
                [error_record("invalid_value", param=key, reason=problem)], exit_code=1
            )

    try:
        _write_param_to_toml(config_path, schema, value, step)
    except (OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record("config_error", param=key, reason=str(exc))], exit_code=1
        )

    record = {
        "param": key,
        "value": value,
        "status": "set",
        "source": "ecc.toml",
        "applies_to": "next fresh/overwrite run",
    }
    registered = _registered_workspace_names(ctx.project_dir)
    if registered:
        record["registered_workspaces"] = ", ".join(registered)
    record["workspace_hint"] = (
        "existing workspaces ignore ecc.toml params; apply to one with: "
        + disclosure_cmd(
            f"ecc param set {key} <value> --workspace NAME",
            ctx.project,
        )
    )
    return CommandResult.ok([record])


def param_unset(args, ctx: CommandContext) -> CommandResult:
    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers import workspace_params

        return workspace_params.param_unset(args, ctx)
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    key = args.key

    step, schema, key_error = parse_step_key(key)
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
    if key_error is not None:
        return _step_key_error(key, step, key_error)
    flow_error = _parameter_flow_error(schema, ctx)
    if flow_error is not None:
        return flow_error

    config_path = find_config_path(ctx.project_dir)
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

    try:
        removed = _remove_param_from_toml(config_path, schema, step)
    except (OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record("config_error", param=key, reason=str(exc))], exit_code=1
        )

    if removed:
        return CommandResult.ok(
            [
                {
                    "param": key,
                    "status": "unset",
                    "value": schema.default_for(_project_pdk(ctx)),
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
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides, pdk=_project_pdk(ctx))

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
        records.extend(step_diff_records(rp, toml_overrides))

    if not records:
        return CommandResult.ok([{"diff_status": "clean"}])

    return CommandResult.ok(records)


def param_apply(args, ctx: CommandContext) -> CommandResult:
    """Apply a parameter batch at Project or managed Workspace scope."""
    try:
        parsed_sets = _parse_parameter_sets(args.sets)
        _validate_parameter_patch(parsed_sets, args.unsets)
        values = _parse_parameter_values(parsed_sets, ctx)
    except ValueError as exc:
        return CommandResult.err([error_record("invalid_parameter_patch", reason=str(exc))])
    if args.commit_step_output and args.step is None:
        return CommandResult.err(
            [
                error_record(
                    "invalid_parameter_scope",
                    reason="--commit-step-output requires --step and --workspace",
                )
            ]
        )
    if args.workspace is None:
        if args.step is not None or args.commit_step_output or args.expected_revision is not None:
            return CommandResult.err(
                [
                    error_record(
                        "invalid_parameter_scope",
                        reason="--step/--expected-revision require --workspace",
                    )
                ]
            )
        manifest_error = _manifest_mode_error(ctx)
        if manifest_error is not None:
            return manifest_error
        from chipcompiler.cli.project.project_application import (
            ProjectApplicationError,
            apply_project,
        )

        encoded_sets = tuple(f"{key}={raw}" for key, raw in parsed_sets)
        try:
            changed = apply_project(
                ctx.project_dir,
                sets=encoded_sets,
                unsets=args.unsets,
                add_rtl=(),
                remove_rtl=(),
                blocking=not args.no_wait,
            )
        except BlockingIOError:
            return CommandResult.err([error_record("project_busy")], exit_code=20)
        except ProjectApplicationError as exc:
            return CommandResult.err([error_record(exc.code, param=exc.key, reason=str(exc))])
        return CommandResult.ok(
            [
                {
                    "status": "applied",
                    "scope": "project",
                    "changed": ", ".join(changed),
                }
            ]
        )

    if ctx.manifest_error or ctx.project_state != "manifest" or ctx.run_id is None:
        return CommandResult.err(
            [
                error_record(
                    "workspace_param_requires_managed_workspace",
                    reason=ctx.manifest_error
                    or "--workspace must select a workspace declared in project.json",
                )
            ]
        )
    from pathlib import Path

    from chipcompiler.engine import apply_workspace_parameters
    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.utility.workspace_lock import workspace_lock

    try:
        with workspace_lock(Path(ctx.run_dir), blocking=not args.no_wait):
            current = read_engineering_snapshot_from_directory(ctx.run_dir)
            expected = args.expected_revision or current["workspaceRevision"]
            updated = apply_workspace_parameters(
                ctx.run_dir,
                expected,
                values,
                args.unsets,
                step_id=args.step,
                commit_step_output=args.commit_step_output,
                command_id=args.command_id,
            )
            committed = read_engineering_snapshot_from_directory(ctx.run_dir)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, reason=str(exc), **exc.details)],
            exit_code=21 if exc.code == "revision_conflict" else 1,
        )
    except Exception as exc:
        return CommandResult.err(
            [error_record("workspace_parameter_apply_failed", reason=str(exc))]
        )
    return CommandResult.ok(
        [
            {
                "status": "applied",
                "scope": "workspace",
                "workspace_id": ctx.run_id,
                "workspace": str(updated.directory),
                "workspace_revision": committed["workspaceRevision"],
            }
        ]
    )


def _parse_parameter_sets(values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    parsed = []
    seen = set()
    for value in values:
        key, separator, raw = value.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"Invalid --set: {value}")
        if key in seen:
            raise ValueError(f"Duplicate --set: {key}")
        seen.add(key)
        parsed.append((key, raw))
    return tuple(parsed)


def _validate_parameter_patch(sets: tuple[tuple[str, str], ...], unsets: tuple[str, ...]) -> None:
    if not sets and not unsets:
        raise ValueError("At least one --set or --unset is required")
    unset_keys = set(unsets)
    if len(unset_keys) != len(unsets):
        raise ValueError("Duplicate --unset")
    overlap = {key for key, _raw in sets} & unset_keys
    if overlap:
        raise ValueError(f"Parameter cannot be set and unset: {min(overlap)}")
    for key in (*[key for key, _raw in sets], *unsets):
        # Step-qualified keys (``placement:place.x``) are scoped by the apply target.
        if lookup_schema(split_step_key(key)[1]) is None:
            raise ValueError(f"Unknown parameter: {key}")


def _parse_parameter_values(
    sets: tuple[tuple[str, str], ...], ctx: CommandContext
) -> dict[str, object]:
    result = {}
    for key, raw in sets:
        schema = lookup_schema(split_step_key(key)[1])
        assert schema is not None
        flow_error = _parameter_flow_error(schema, ctx)
        if flow_error is not None and ctx.config is not None:
            raise ValueError(f"Parameter is not in the configured flow: {key}")
        try:
            value = parse_value(raw, schema)
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from exc
        errors = validate_value(value, schema, _project_pdk(ctx))
        if errors:
            raise ValueError(f"{key}: {errors[0]}")
        result[key] = value
    return result


def _registered_workspace_names(project_dir: str) -> list[str]:
    """Workspace ids registered in project.json ([] for non-manifest projects)."""
    from chipcompiler.project.manifest import ManifestError, load_manifest

    try:
        manifest = load_manifest(project_dir)
    except (ManifestError, OSError):
        return []
    return [workspace.workspace_id for workspace in manifest.workspaces]


def _load_toml_overrides(project_dir: str) -> tuple[dict[str, object], list[str]]:
    from chipcompiler.cli.project.config import load_project_config

    config_path = find_config_path(project_dir)
    if config_path is None:
        return {}, []

    try:
        cfg = load_project_config(config_path)
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"unreadable ecc.toml: {exc}"]
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
def _write_param_to_toml(config_path: str, schema, value: object, step: str | None = None) -> None:
    with open(config_path) as f:
        original = f.read()

    new_text = set_parameter(original, schema, value, step)
    write_text_atomic(config_path, new_text)


def _remove_param_from_toml(config_path: str, schema, step: str | None = None) -> bool:
    with open(config_path) as f:
        original = f.read()

    result = unset_parameter(original, schema, step)
    if result is None:
        return False

    write_text_atomic(config_path, result)
    return True
