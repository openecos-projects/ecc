"""``ecc param edit``: edit a project's or a workspace's parameters in the terminal.

The editor only collects the changes. They are confirmed, then applied as
one ``ecc param apply`` batch (:func:`param_apply`), the command an agent
runs, so both paths parse, validate, write and invalidate steps alike.
"""

import json
from collections.abc import Collection
from dataclasses import replace
from typing import TYPE_CHECKING

from chipcompiler.cli.core.inputs import ParamApplyInput, ParamEditInput
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.rtl2gds import normalize_flow_step

if TYPE_CHECKING:
    from rich.console import Console

    from chipcompiler.cli.interactive.param_edit import ParamRow
    from chipcompiler.cli.interactive.terminal import KeyReader
    from chipcompiler.data.parameter_schema import ParamSchema


def param_edit(args: ParamEditInput, ctx: CommandContext) -> CommandResult:
    from rich.console import Console

    from chipcompiler.cli.interactive.terminal import interactive_terminal, terminal_keys

    if ctx.output_mode is not OutputMode.TEXT or not interactive_terminal():
        return CommandResult.err(
            [
                error_record(
                    "param_edit_requires_terminal",
                    reason="the parameter editor needs an interactive terminal; use "
                    "ecc param apply --set KEY=VALUE / --unset KEY",
                )
            ]
        )
    with terminal_keys() as read_key:
        return edit_and_apply(
            ctx,
            args,
            group=args.step,
            console=Console(highlight=False),
            read_key=read_key,
        )


def edit_and_apply(
    ctx: CommandContext,
    args: ParamEditInput,
    *,
    group: str | None = None,
    steps: Collection[str] | None = None,
    console: "Console",
    read_key: "KeyReader",
) -> CommandResult:
    """Edit the parameters of ``args.workspace`` (or the project), then apply the changes.

    *group* opens one parameter group (a step name such as ``cts``); *steps*
    keeps only the workspace parameters that affect those flow steps.
    """
    from chipcompiler.cli.command_handlers.param import param_apply
    from chipcompiler.cli.interactive.param_edit import changes_table, edit_parameters
    from chipcompiler.cli.interactive.terminal import confirm_write

    rows = workspace_rows(ctx, steps) if args.workspace else project_rows(ctx)
    if isinstance(rows, CommandResult):
        return rows
    if group:
        identity = normalize_flow_step(group).casefold()
        rows = [row for row in rows if identity in _row_steps(row)]
        if not rows:
            return CommandResult.err([error_record("unknown_step", step=group)])
    if not rows:
        return CommandResult.err(
            [error_record("no_editable_parameters", workspace=args.workspace or "")]
        )
    scope = f"workspace {args.workspace}" if args.workspace else "project (ecc.toml)"
    changes = edit_parameters(
        rows,
        title=f"Parameters of the {scope}",
        check=_check,
        console=console,
        read_key=read_key,
    )
    if changes is None:
        return _cancelled()
    if not confirm_write(changes_table(rows, changes), console=console, read_key=read_key):
        return _cancelled()
    return param_apply(
        ParamApplyInput(
            output=args.output,
            project=args.project,
            sets=tuple(f"{param}={text}" for param, text in changes.sets),
            unsets=changes.unsets,
            workspace=args.workspace,
        ),
        ctx,
    )


def workspace_rows(
    ctx: CommandContext, steps: Collection[str] | None = None
) -> "list[ParamRow] | CommandResult":
    """The parameters a workspace can change, in its current state.

    A parameter only the full workspace refresh can change (a PDK path, or
    one without a step) is left out; so is one for a step outside the flow,
    or outside *steps* when given. ``base`` is the value before this
    workspace's override.
    """
    from chipcompiler.data import load_workspace
    from chipcompiler.data.parameter_schema import list_schemas
    from chipcompiler.data.workspace_parameters import (
        workspace_param_diff,
        workspace_param_step,
        workspace_param_value,
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
    workspace = load_workspace(ctx.run_dir)
    if workspace is None:
        return CommandResult.err([error_record("workspace_invalid", workspace=ctx.run_id)])
    in_flow = {
        normalize_flow_step(str(step.get("name", ""))).casefold() for step in workspace.flow.steps()
    }
    kept = in_flow
    if steps is not None:
        kept = in_flow & {normalize_flow_step(step).casefold() for step in steps}
    overrides = {record["key"]: record for record in workspace_param_diff(workspace)}
    rows = []
    for schema in list_schemas():
        if schema.pdk_target is not None:
            continue
        try:
            step = workspace_param_step(schema)
            value = workspace_param_value(workspace, schema)
        except ValueError:
            continue
        if step is not None and normalize_flow_step(step).casefold() not in kept:
            continue
        override = overrides.get(schema.param)
        base = override["baseline"] if override is not None else value
        rows.append(_row(schema, value, base, overridden=override is not None))
    return rows


def project_rows(ctx: CommandContext) -> "list[ParamRow] | CommandResult":
    """The project's parameters (``ecc.toml``) for the steps of its preset."""
    from chipcompiler.cli.command_handlers.param import (
        _load_toml_overrides,
        _manifest_mode_error,
        _parameter_flow_step,
    )
    from chipcompiler.data.parameter_schema import resolve_parameters
    from chipcompiler.rtl2gds import get_flow_builders

    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    toml_overrides, errors = _load_toml_overrides(ctx.project_dir)
    if errors:
        return CommandResult.err(
            [error_record("invalid_param_config", reason=error) for error in errors]
        )
    builder = get_flow_builders().get(getattr(ctx.config, "flow_preset", ""))
    in_flow = (
        {normalize_flow_step(step).casefold() for step, _tool, _state in builder()}
        if builder is not None
        else set()
    )
    resolved, _errors = resolve_parameters(toml_overrides=toml_overrides)
    return [
        _row(item.schema, item.value, item.default, overridden=item.is_explicit)
        for item in resolved
        if not in_flow
        or item.schema.applies == "all"
        or _parameter_flow_step(item.schema.applies).casefold() in in_flow
    ]


def workspace_context(ctx: CommandContext, workspace_id: str, directory: str) -> CommandContext:
    """*ctx* selecting another managed workspace of the same project.

    The selection is made, so an error about selecting one (``workspace_required``
    when the command named none) no longer applies.
    """
    return replace(
        ctx,
        run_dir=directory,
        run_id=workspace_id,
        workspace_path_explicit=False,
        manifest_error=None,
    )


def _row(schema: "ParamSchema", value: object, base: object, *, overridden: bool) -> "ParamRow":
    from chipcompiler.cli.interactive.param_edit import ParamRow

    hints = []
    if schema.choices is not None:
        hints.append("{" + ", ".join(str(choice) for choice in schema.choices) + "}")
    if schema.range is not None:
        hints.append(f"[{schema.range[0]}, {schema.range[1]}]")
    if schema.unit is not None:
        hints.append(schema.unit)
    return ParamRow(
        param=schema.param,
        group=schema.group,
        value=value_text(value),
        base=value_text(base),
        overridden=overridden,
        kind=schema.type,
        hint=" ".join(hints),
        description=schema.description,
    )


def _row_steps(row: "ParamRow") -> set[str]:
    """The step spellings ``--step`` matches for *row*: its group and the step it applies to."""
    from chipcompiler.data.parameter_schema import lookup_schema

    schema = lookup_schema(row.param)
    applies = schema.applies if schema is not None else row.group
    return {normalize_flow_step(row.group).casefold(), normalize_flow_step(applies).casefold()}


def value_text(value: object) -> str:
    """*value* as ``--set`` takes it: strings as they are, anything else as JSON."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def _check(param: str, text: str) -> str | None:
    from chipcompiler.data.parameter_schema import lookup_schema, parse_value, validate_value

    schema = lookup_schema(param)
    if schema is None:
        return f"unknown parameter {param}"
    try:
        value = parse_value(text, schema)
    except ValueError as exc:
        return str(exc)
    errors = validate_value(value, schema)
    return errors[0] if errors else None


def _cancelled() -> CommandResult:
    return CommandResult.ok([{"record": "param_edit", "status": "cancelled"}])
