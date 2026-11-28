"""Prepare Workspace creation and orchestrate draft/preview creation directly."""

import hashlib
import uuid
from dataclasses import replace
from pathlib import Path

from chipcompiler.cli.core.inputs import RunInput, WorkspaceCreateInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.preparation import (
    preflight_fresh_setup,
    resolve_run_setup,
    validate_run_setup,
)


def build_create_run_input(
    command_input: WorkspaceCreateInput, ctx: CommandContext
) -> RunInput | CommandResult:
    target = Path(ctx.run_dir).expanduser().absolute()
    project = Path(ctx.project_dir).expanduser().resolve()
    if target.parent.resolve() != project:
        return CommandResult.err(
            [
                error_record(
                    "workspace_path_outside_standard_parent",
                    path=str(target),
                    reason="new Workspaces must be direct children of the Project root",
                )
            ]
        )
    raw_draft = command_input.draft
    draft_id = hashlib.sha256(raw_draft.encode()).hexdigest() if raw_draft is not None else None
    return RunInput(
        output=command_input.output,
        project=command_input.project,
        workspace=command_input.workspace,
        from_step=command_input.from_step,
        to_step=command_input.to_step,
        param_set=command_input.param_set,
        command_id=command_input.command_id or str(uuid.uuid4()),
        no_wait=command_input.no_wait,
        create_draft_id=draft_id,
    )


def create_draft_or_preview_workspace(
    command_input: WorkspaceCreateInput,
    ctx: CommandContext,
) -> CommandResult:
    run_input = build_create_run_input(command_input, ctx)
    if isinstance(run_input, CommandResult):
        return run_input
    if ctx.project_state == "legacy":
        from chipcompiler.cli.core.records import legacy_workspace_error_record

        return CommandResult.err([legacy_workspace_error_record()])
    if ctx.manifest_error:
        return CommandResult.err(
            [error_record(ctx.manifest_error.split(":", 1)[0], reason=ctx.manifest_error)]
        )

    project = Path(ctx.project_dir).resolve()
    target = Path(ctx.run_dir)
    target = target.parent.resolve() / target.name
    supplied = project / (command_input.path or command_input.workspace)
    if supplied.is_symlink():
        return CommandResult.err(
            [
                error_record(
                    "run_exists",
                    workspace_id=ctx.run_id,
                    workspace=str(supplied),
                    reason=f"Workspace is a symbolic link: {supplied}",
                )
            ]
        )
    ctx = replace(ctx, project_dir=str(project), run_dir=str(target))
    raw_draft = command_input.draft
    if raw_draft is not None and target.name != ctx.run_id:
        return CommandResult.err(
            [error_record("workspace_conflict", reason="Draft Workspace path must match its ID")]
        )

    if command_input.preview:
        return _preview_creation(run_input, ctx, target, raw_draft)

    assert raw_draft is not None
    return _create_from_draft(run_input, ctx, target, raw_draft)


def _preview_destination_error(
    project: Path, target: Path, run_name: str, *, reuse_empty: bool
) -> CommandResult | None:
    from chipcompiler.cli.project.draft import validate_draft_destination

    try:
        validate_draft_destination(project, target, reuse_empty=reuse_empty)
    except FileExistsError as exc:
        return CommandResult.err(
            [
                error_record(
                    "run_exists", workspace_id=run_name, workspace=str(target), reason=str(exc)
                )
            ]
        )
    except OSError as exc:
        return CommandResult.err(
            [
                error_record(
                    "workspace_failed",
                    workspace_id=run_name,
                    workspace=str(target),
                    reason=str(exc),
                )
            ]
        )
    return None


def _preview_creation(
    run_input: RunInput,
    ctx: CommandContext,
    target: Path,
    raw_draft: str | None,
) -> CommandResult:
    project = Path(ctx.project_dir)
    run_name = ctx.run_id or target.name
    if (target / "home" / "flow.json").is_file():
        return CommandResult.err(
            [error_record("workspace_conflict", reason=f"Workspace already exists: {target}")]
        )
    destination_error = _preview_destination_error(
        project, target, run_name, reuse_empty=ctx.workspace_path_explicit
    )
    if destination_error is not None:
        return destination_error
    if raw_draft is not None:
        from chipcompiler.cli.project.draft import prepare_creation_draft

        prepared = prepare_creation_draft(ctx, raw_draft)
        if isinstance(prepared, CommandResult):
            return prepared
        ctx, _draft = prepared
    setup = resolve_run_setup(run_input, ctx, execute_flow=False)
    if isinstance(setup, CommandResult):
        return setup
    if not setup.fresh_target:
        return CommandResult.err(
            [
                error_record(
                    "workspace_conflict", reason=f"Workspace already exists: {setup.run_dir}"
                )
            ]
        )
    validation_error = validate_run_setup(setup, ctx, check_pdk_files=False)
    if validation_error is not None:
        return validation_error
    return _preview_workspace_creation(setup.cfg, setup.flow_config)


def _create_from_draft(
    run_input: RunInput,
    ctx: CommandContext,
    target: Path,
    raw_draft: str,
) -> CommandResult:
    from chipcompiler.cli.project.draft import prepare_creation_draft
    from chipcompiler.cli.project.rtl_import import RtlImportError
    from chipcompiler.cli.project.run_prepare import build_fresh_workspace, workspace_failed_result
    from chipcompiler.engine.workspace.paths import (
        finalize_staged_workspace_configs,
        relocate_staged_workspace_metadata,
    )
    from chipcompiler.utility.workspace_lock import workspace_lock

    run_name = ctx.run_id or target.name
    with workspace_lock(target, blocking=not run_input.no_wait):
        if (target / "home" / "flow.json").is_file():
            return _existing_draft_workspace_locked(run_input, ctx, str(target), run_name)
        prepared = prepare_creation_draft(ctx, raw_draft)
        if isinstance(prepared, CommandResult):
            return prepared
        ctx, draft = prepared
        setup = resolve_run_setup(run_input, ctx, execute_flow=False)
        if isinstance(setup, CommandResult):
            return setup
        if not setup.fresh_target:
            return _existing_draft_workspace_locked(run_input, ctx, setup.run_dir, setup.run_name)
        validation_error = validate_run_setup(setup, ctx, check_pdk_files=True)
        if validation_error is not None:
            return validation_error
        preflight, warnings = preflight_fresh_setup(setup, ctx.project)
        if preflight is not None:
            return preflight
        try:
            with draft.build_target(
                Path(setup.run_dir), setup.cfg, reuse_empty=ctx.workspace_path_explicit
            ) as (built, build_cfg):
                try:
                    constructed = build_fresh_workspace(
                        run_input,
                        ctx,
                        build_cfg,
                        build_dir=built,
                        run_dir=setup.run_dir,
                        run_name=setup.run_name,
                        cli_overrides=setup.cli_overrides,
                        flow_config=setup.flow_config,
                        record_create_command=bool(run_input.command_id),
                    )
                    finalize_staged_workspace_configs(constructed.workspace, Path(setup.run_dir))
                    relocate_staged_workspace_metadata(
                        constructed.workspace.directory,
                        Path(setup.run_dir),
                    )
                except Exception as exc:
                    return workspace_failed_result(setup.run_name, setup.run_dir, str(exc) or None)
                draft.publish(
                    setup.cfg,
                    setup.flow_config,
                    Path(setup.run_dir),
                    built=built,
                    reuse_empty=ctx.workspace_path_explicit,
                    blocking=not run_input.no_wait,
                )
                return CommandResult.ok(
                    [
                        *warnings,
                        {
                            "workspace_id": setup.run_name,
                            "workspace": setup.run_dir,
                            "status": "refreshed",
                            "run": disclosure_cmd("ecc run", ctx.project, setup.run_name),
                        },
                    ]
                )
        except BlockingIOError:
            raise
        except RtlImportError as exc:
            return CommandResult.err(
                [
                    error_record(
                        exc.code,
                        workspace_id=setup.run_name,
                        workspace=setup.run_dir,
                        reason=str(exc),
                    )
                ]
            )
        except (OSError, ValueError) as exc:
            code = "run_exists" if isinstance(exc, FileExistsError) else "workspace_failed"
            return CommandResult.err(
                [
                    error_record(
                        code, workspace_id=setup.run_name, workspace=setup.run_dir, reason=str(exc)
                    )
                ]
            )


def _existing_draft_workspace_locked(
    command_input: RunInput, ctx: CommandContext, run_dir: str, run_name: str
) -> CommandResult:
    from chipcompiler.project.manifest import load_manifest

    target = Path(run_dir)
    entry = load_manifest(ctx.project_dir).find_workspace(run_name)
    if (
        entry
        and Path(entry.workspace_path).resolve() == target.resolve()
        and repeats_recorded_create(command_input, run_dir, run_name)
    ):
        return CommandResult.ok(
            [{"workspace_id": run_name, "workspace": run_dir, "status": "created"}]
        )
    return CommandResult.err(
        [error_record("workspace_conflict", reason=f"Workspace already exists: {target}")]
    )


def _preview_workspace_creation(cfg, flow_config) -> CommandResult:
    from chipcompiler.cli.project.config import resolve_max_parallel_steps
    from chipcompiler.cli.project.flow_selection import project_flow_plan, selection_warnings

    plan = project_flow_plan(cfg, flow_config)
    return CommandResult.ok(
        [
            {
                "record": "workspace_preview",
                "steps": [step.name for step in plan.steps if step.enabled] if plan else [],
                "max_parallel_steps": resolve_max_parallel_steps(cfg),
            },
            *selection_warnings(cfg, flow_config),
        ]
    )


def create_command_spec(command_input: RunInput, run_name: str) -> dict:
    """The request `workspace create` records under its command id."""
    draft_id = command_input.create_draft_id
    return {
        "workspace": run_name,
        "from": command_input.from_step,
        "to": command_input.to_step,
        "parameters": list(command_input.param_set),
        **({"draft": draft_id} if draft_id else {}),
    }


def repeats_recorded_create(command_input: RunInput, run_dir: str, run_name: str) -> bool:
    """True when this exact `workspace create` request already built the workspace."""
    if not command_input.command_id:
        return False
    from chipcompiler.engine.workspace.lifecycle import (
        WorkspaceLifecycleError,
        command_retry_matches,
        workspace_command_fingerprint,
    )

    fingerprint = workspace_command_fingerprint(
        "create",
        create_command_spec(command_input, run_name),
        None,
        command_input.expected_revision,
    )
    try:
        return command_retry_matches(Path(run_dir), command_input.command_id, fingerprint)
    except (WorkspaceLifecycleError, OSError, ValueError):
        # A reused id with another request, or an unreadable ledger: not a retry.
        return False
