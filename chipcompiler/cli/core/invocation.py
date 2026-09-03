import os
import sys
from collections.abc import Callable
from typing import Protocol, TypeVar

import typer

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.cli.inspection.discovery import resolve_run_dir
from chipcompiler.cli.project.config import (
    ConfigUnreadableError,
    InvalidFlowRun,
    config_run_id_from,
    load_run_config,
    resolve_project_dir,
)


class CommandInput(Protocol):
    # Read-only members: the frozen input dataclasses satisfy these.
    @property
    def output(self) -> OutputOptions: ...
    @property
    def project(self) -> ProjectOptions: ...


CommandInputT = TypeVar("CommandInputT", bound=CommandInput)
CommandHandler = Callable[[CommandInputT, CommandContext], CommandResult]


def output_mode(*, json_output: bool, jsonl: bool, plain: bool) -> OutputMode:
    if jsonl:
        return OutputMode.JSONL
    if json_output:
        return OutputMode.JSON
    if plain:
        return OutputMode.PLAIN
    return OutputMode.TEXT


def _resolve_manifest_run(
    project_dir: str, cli_run_id: str | None
) -> tuple[str, str | None, str | None]:
    """Resolve the run directory from a project.json manifest.

    Returns (run_dir, run_id, error): exactly one non-archived workspace
    auto-selects; otherwise --run-id selects by workspace_id or declared
    path tail. Unknown ids fail with workspace_not_declared (the error text
    lists the declared ids).
    """
    from chipcompiler.cli.project.manifest import load_manifest
    from chipcompiler.cli.project.run_prepare import invalid_single_segment_id

    manifest = load_manifest(project_dir)
    active = manifest.active_workspaces()

    if cli_run_id is None:
        if len(active) == 1:
            return active[0].workspace_path, active[0].workspace_id, None
        ids = ", ".join(w.workspace_id for w in active) or "(none)"
        return (
            os.path.join(project_dir, "default"),
            None,
            f"workspace_not_declared: --run-id required; declared workspaces: {ids}",
        )

    if invalid_single_segment_id(cli_run_id):
        return (
            os.path.join(project_dir, "default"),
            None,
            f"invalid_run_id: {cli_run_id!r} is not a single path segment inside the project",
        )

    match = manifest.find_workspace(cli_run_id)
    if match is not None:
        return match.workspace_path, match.workspace_id, None
    ids = ", ".join(w.workspace_id for w in active) or "(none)"
    return (
        os.path.join(project_dir, cli_run_id),
        cli_run_id,
        f"workspace_not_declared: unknown workspace {cli_run_id!r}; declared workspaces: {ids}",
    )


def build_context(command_input: CommandInput) -> CommandContext:
    project = command_input.project.project
    project_dir = resolve_project_dir(project)

    cli_run_id = command_input.project.run_id
    config_error = None
    try:
        cfg = load_run_config(project_dir)
    except ConfigUnreadableError as exc:
        cfg = None
        config_error = str(exc)

    from chipcompiler.cli.project.manifest import (
        ManifestError,
        classify_project,
    )

    project_state = classify_project(project_dir)
    manifest_error = None

    if project_state == "manifest":
        # Manifest projects use the manifest workspaces table for discovery
        # even when an ecc.toml also exists (config values still layer the
        # ecc.toml above the manifest base).
        try:
            run_dir, run_id, manifest_error = _resolve_manifest_run(project_dir, cli_run_id)
        except ManifestError as exc:
            run_dir, run_id = os.path.join(project_dir, "default"), cli_run_id
            manifest_error = f"manifest_invalid: {exc}"
    else:
        configured = config_run_id_from(cfg)
        if isinstance(configured, InvalidFlowRun):
            if cli_run_id is None:
                config_error = configured.problem
            configured = None

        run_dir, run_id = resolve_run_dir(
            project_dir, cli_run_id if cli_run_id is not None else configured
        )

    mode = output_mode(
        json_output=command_input.output.json,
        jsonl=command_input.output.jsonl,
        plain=command_input.output.plain,
    )

    return CommandContext(
        project_dir=project_dir,
        project=project,
        run_dir=run_dir,
        run_id=run_id,
        output_mode=mode,
        config_error=config_error,
        config=cfg,
        project_state=project_state,
        manifest_error=manifest_error,
    )


def _should_colorize():
    from chipcompiler.cli.rendering.pretty import supports_color

    return supports_color(file=sys.stdout)


def _with_legacy_hint(command: str, command_input, result, ctx):
    """Append the legacy-layout hint at the command-result boundary.

    run/check/status on a legacy runs/ project carry the hint on EVERY
    outcome — success, config error, missing/corrupt flow, or run
    failure — with exit code and other records untouched. ``run
    --workspace`` targets an explicit workspace, not the project layout,
    and stays undecorated.
    """
    if (
        command not in ("run", "check", "status")
        or ctx.project_state != "legacy"
        or getattr(command_input, "workspace", None) is not None
    ):
        return result
    from chipcompiler.cli.core.records import legacy_layout_hint_record

    return CommandResult(
        records=(*result.records, legacy_layout_hint_record(ctx.project)),
        exit_code=result.exit_code,
    )


def _with_config_shadow_hint(command: str, result, ctx):
    """Append the shadowed-config warning at the command-result boundary.

    run/check/status on a workspace whose home/ holds BOTH the canonical
    params.toml and a legacy parameters.json carry the warning on every
    outcome: the JSON is inert, and a user editing it would otherwise see
    nothing happen. One lexists pair per command; no workspace load, no
    file mutation — deleting the JSON stays the user's call.
    """
    if command not in ("run", "check", "status"):
        return result
    from chipcompiler.cli.core.records import warning_record
    from chipcompiler.data.workspace_config import (
        LEGACY_PARAMETERS_FILENAME,
        WORKSPACE_CONFIG_FILENAME,
    )

    home = os.path.join(ctx.run_dir, "home")
    if not (
        os.path.isfile(os.path.join(home, WORKSPACE_CONFIG_FILENAME))
        and os.path.isfile(os.path.join(home, LEGACY_PARAMETERS_FILENAME))
    ):
        return result
    return CommandResult(
        records=(
            *result.records,
            warning_record(
                "workspace_config_shadowed",
                reason="home/params.toml wins over home/parameters.json; "
                "the legacy JSON is inert — delete it to silence this",
            ),
        ),
        exit_code=result.exit_code,
    )


def execute_command(
    command: str,
    command_input: CommandInputT,
    handler: CommandHandler[CommandInputT],
    render_key: str | None = None,
) -> None:
    ctx = build_context(command_input)
    result = _with_legacy_hint(command, command_input, handler(command_input, ctx), ctx)
    result = _with_config_shadow_hint(command, result, ctx)
    color = _should_colorize()
    selected_render_key = render_key or command

    from chipcompiler.cli.rendering.renderers import render_command_result

    render_command_result(command, selected_render_key, result, ctx, command_input, color=color)

    raise typer.Exit(code=result.exit_code)
