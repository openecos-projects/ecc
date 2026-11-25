"""Prepare Workspace creation and recognize retries of a recorded request."""

import hashlib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.cli.core.inputs import RunInput, WorkspaceCreateInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult

if TYPE_CHECKING:
    from chipcompiler.cli.project.config import ProjectConfig
    from chipcompiler.cli.project.draft import CreationDraft
    from chipcompiler.cli.project.flow_selection import FlowConfig


def prepare_workspace_creation(
    command_input: WorkspaceCreateInput, ctx: CommandContext
) -> tuple[RunInput, CommandContext, "CreationDraft | None"] | CommandResult:
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
    run_input = RunInput(
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
    if raw_draft is None or ctx.manifest_error:
        return run_input, ctx, None
    if target.name != ctx.run_id:
        return CommandResult.err(
            [error_record("workspace_conflict", reason="Draft Workspace path must match its ID")]
        )
    if (target / "home" / "flow.json").is_file():
        return existing_draft_workspace(
            run_input, ctx, str(target), ctx.run_id or target.name, preview=command_input.preview
        )

    from chipcompiler.cli.project.draft import prepare_creation_draft

    prepared = prepare_creation_draft(ctx, raw_draft)
    if isinstance(prepared, CommandResult):
        return prepared
    ctx, draft = prepared
    return run_input, ctx, draft


def existing_draft_workspace(
    command_input: RunInput, ctx: CommandContext, run_dir: str, run_name: str, *, preview: bool
) -> CommandResult:
    from chipcompiler.cli.project.draft import (
        DRAFT_PROJECT_CHANGES_SKIPPED,
        require_draft_published,
    )
    from chipcompiler.project.manifest import load_manifest
    from chipcompiler.utility.workspace_lock import workspace_lock

    target = Path(run_dir)
    if not preview:
        with workspace_lock(target, blocking=not command_input.no_wait):
            entry = load_manifest(ctx.project_dir).find_workspace(run_name)
            if (
                entry
                and Path(entry.workspace_path).resolve() == target.resolve()
                and repeats_recorded_create(command_input, run_dir, run_name)
            ):
                skipped = entry.raw.get(DRAFT_PROJECT_CHANGES_SKIPPED)
                if isinstance(skipped, str):
                    return draft_project_changes_error(run_dir, run_name, skipped)
                return CommandResult.ok(
                    [{"workspace_id": run_name, "workspace": run_dir, "status": "created"}]
                )
            try:
                require_draft_published(Path(ctx.project_dir), target)
            except OSError as exc:
                return CommandResult.err([error_record("workspace_draft_pending", reason=str(exc))])
    return CommandResult.err(
        [error_record("workspace_conflict", reason=f"Workspace already exists: {target}")]
    )


def draft_project_changes_error(run_dir: str, run_name: str, reason: str) -> CommandResult:
    return CommandResult.err(
        [
            error_record(
                "workspace_draft_project_changes_skipped",
                reason=reason,
                workspace_id=run_name,
                workspace=run_dir,
                workspace_created=True,
            )
        ]
    )


def publish_workspace_creation(
    draft: "CreationDraft",
    cfg: "ProjectConfig",
    flow_config: "FlowConfig | None",
    command_input: RunInput,
    ctx: CommandContext,
    run_dir: str,
    run_name: str,
    warnings: list[dict],
) -> CommandResult:
    from chipcompiler.cli.project.draft import DraftPublicationPending

    fields = {"workspace_id": run_name, "workspace": run_dir}
    try:
        publication = draft.publish(
            cfg,
            flow_config,
            Path(run_dir),
            reuse_empty=ctx.workspace_path_explicit,
            blocking=not command_input.no_wait,
        )
    except DraftPublicationPending as exc:
        return CommandResult.err(
            [error_record("workspace_draft_pending", reason=str(exc), **fields)]
        )
    if not publication.workspace_created:
        return CommandResult.err(
            [
                error_record(
                    "workspace_conflict", reason=publication.project_changes_skipped, **fields
                )
            ]
        )
    if publication.project_changes_skipped:
        return draft_project_changes_error(run_dir, run_name, publication.project_changes_skipped)
    return CommandResult.ok(
        [
            *warnings,
            {
                **fields,
                "status": "refreshed",
                "run": disclosure_cmd("ecc run", ctx.project, run_name),
            },
        ]
    )


def preview_workspace_creation(cfg, flow_config) -> CommandResult:
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
