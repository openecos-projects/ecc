"""``ecc workspace fork``: a new managed workspace that continues from another one.

The fork copies the source workspace, keeps the results of the steps before
``--from`` and resets that step and the steps after it (``--to`` bounds them
too), under a new identity that project.json registers with its lineage
(``source_workspace_id`` and ``branch_from``). The source is not modified,
and the fork keeps its parameters until they are changed.

Without TARGET, a terminal picker asks for the source (unless given), the
restart step and the name, and can open the parameter editor on the new
workspace; scripts and agents pass SOURCE and TARGET.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.cli.core.inputs import ParamEditInput, WorkspaceForkInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode

if TYPE_CHECKING:
    from chipcompiler.cli.interactive.workspace_fork import SourceRow, StepRow
    from chipcompiler.project.manifest import ProjectManifest


def fork_workspace(command_input: WorkspaceForkInput, ctx: CommandContext) -> CommandResult:
    if ctx.project_state != "manifest":
        return _requires_managed_source(ctx)
    if command_input.workspace is None:
        # No SOURCE to resolve: the picker lists the workspaces of project.json,
        # so the context's "select a workspace" error does not apply.
        return _fork_interactively(command_input, ctx)
    if ctx.manifest_error or ctx.run_id is None:
        return _requires_managed_source(ctx)
    if command_input.target_workspace is None:
        return _fork_interactively(command_input, ctx)
    return fork(
        ctx,
        source_id=ctx.run_id,
        source_dir=ctx.run_dir,
        target_id=command_input.target_workspace,
        from_step=command_input.from_step or "",
        to_step=command_input.to_step or "",
        command_id=command_input.command_id,
        no_wait=command_input.no_wait,
    )


def fork(
    ctx: CommandContext,
    *,
    source_id: str,
    source_dir: str,
    target_id: str,
    from_step: str,
    to_step: str,
    command_id: str = "",
    no_wait: bool = False,
) -> CommandResult:
    """Fork *source_id* into *target_id* and register it; a failed fork leaves nothing."""
    import shutil
    import uuid

    from chipcompiler.cli.project.run_prepare import invalid_workspace_name
    from chipcompiler.engine.snapshot import read_engineering_snapshot
    from chipcompiler.engine.workspace_derive import derive_workspace
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
    from chipcompiler.project.api import project_manifest_mutator
    from chipcompiler.project.manifest import load_manifest
    from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked

    if invalid_workspace_name(target_id):
        return CommandResult.err([error_record("invalid_workspace", workspace_id=target_id)])
    project = Path(ctx.project_dir).resolve()
    target = project / target_id
    target_existed = target.exists()
    command_id = command_id or str(uuid.uuid4())
    try:
        project_manifest = load_manifest(str(project))
        forked = derive_workspace(
            source_dir,
            target,
            reset_from_step=from_step,
            through_step=to_step,
            command_id=command_id,
            blocking=not no_wait,
            project_id=project_manifest.project_id,
            source_workspace_id=source_id,
            target_workspace_id=target_id,
        )
        with manifest_lock(project, blocking=not no_wait):
            load_manifest(str(project))
            mutation = {
                "type": "register_workspace",
                "workspace_id": target_id,
                "workspace_path": str(target),
                "source_workspace_id": source_id,
                "branch_from": {
                    "source_workspace_id": source_id,
                    **({"source_step": from_step} if from_step else {}),
                },
            }
            if not update_manifest_locked(project, project_manifest_mutator(project, mutation)):
                raise OSError("Project Manifest update failed")
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except (WorkspaceLifecycleError, OSError, ValueError) as exc:
        if not target_existed and target.is_dir() and target != Path(source_dir):
            shutil.rmtree(target, ignore_errors=True)
        code = exc.code if isinstance(exc, WorkspaceLifecycleError) else "workspace_fork_failed"
        return CommandResult.err([error_record(code, reason=str(exc))])
    snapshot = read_engineering_snapshot(forked)
    return CommandResult.ok(
        [
            {
                "workspace_id": target_id,
                "status": "forked",
                "source_workspace_id": source_id,
                "workspace": str(target),
                "workspace_revision": snapshot["workspaceRevision"],
                "run": disclosure_cmd("ecc run", ctx.project, target_id),
            }
        ]
    )


def _fork_interactively(command_input: WorkspaceForkInput, ctx: CommandContext) -> CommandResult:
    from rich.console import Console

    from chipcompiler.cli.command_handlers.param_edit import edit_and_apply, workspace_context
    from chipcompiler.cli.interactive.terminal import interactive_terminal, terminal_keys
    from chipcompiler.cli.interactive.workspace_fork import choose_fork
    from chipcompiler.project.manifest import ManifestError, load_manifest

    if command_input.from_step is not None or command_input.to_step is not None:
        return CommandResult.err(
            [
                error_record(
                    "workspace_fork_requires_target",
                    reason="--from/--to need SOURCE and TARGET; without TARGET the steps "
                    "are chosen in the terminal",
                )
            ]
        )
    try:
        manifest = load_manifest(ctx.project_dir)
    except ManifestError as exc:
        reason = f"manifest_invalid: {exc}"
        return CommandResult.err(
            [error_record("workspace_fork_requires_managed_source", reason=reason)]
        )
    if command_input.workspace is None and not manifest.active_workspaces():
        return CommandResult.err(
            [
                error_record(
                    "workspace_fork_no_source",
                    reason="project.json declares no workspace to fork; create one with ecc run",
                )
            ]
        )
    if ctx.output_mode is not OutputMode.TEXT or not interactive_terminal():
        return CommandResult.err(
            [
                error_record(
                    "workspace_fork_requires_terminal",
                    reason="choosing the fork needs an interactive terminal; pass "
                    "SOURCE TARGET [--from STEP] [--to STEP]",
                )
            ]
        )
    sources, steps, directories = _sources(manifest)
    if command_input.workspace is not None:
        # The source selected on the command line, wherever project.json puts
        # it, skips the source screen: refuse it here as that screen would.
        assert ctx.run_id is not None
        flow = _steps(ctx.run_dir)
        blocked = _blocked(ctx.run_dir, flow)
        if blocked is not None:
            return CommandResult.err(
                [
                    error_record(
                        "workspace_fork_source_unavailable",
                        workspace_id=ctx.run_id,
                        reason=f"{ctx.run_id} cannot be forked: {blocked}",
                    )
                ]
            )
        directories[ctx.run_id] = ctx.run_dir
        steps[ctx.run_id] = flow or []

    def check_name(name: str) -> str | None:
        from chipcompiler.cli.project.run_prepare import invalid_workspace_name

        if invalid_workspace_name(name):
            return f"{name!r} is not a workspace name"
        if _taken(manifest, name):
            return f"{name} already exists"
        return None

    def suggest_name(source: str) -> str:
        number = 1
        while _taken(manifest, f"{source}-{number}"):
            number += 1
        return f"{source}-{number}"

    with terminal_keys() as read_key:
        console = Console(highlight=False)
        choice = choose_fork(
            sources,
            lambda workspace_id: steps.get(workspace_id, []),
            source=ctx.run_id if command_input.workspace is not None else None,
            target=None,
            suggest_name=suggest_name,
            check_name=check_name,
            console=console,
            read_key=read_key,
        )
        if choice is None:
            return CommandResult.ok([{"record": "workspace_fork", "status": "cancelled"}])
        forked = fork(
            ctx,
            source_id=choice.source,
            source_dir=directories[choice.source],
            target_id=choice.target,
            from_step=choice.from_step,
            to_step=choice.to_step or "",
            command_id=command_input.command_id,
            no_wait=command_input.no_wait,
        )
        if forked.exit_code or not choice.edit_parameters:
            return forked
        target_dir = str(Path(ctx.project_dir).resolve() / choice.target)
        edited = edit_and_apply(
            workspace_context(ctx, choice.target, target_dir),
            ParamEditInput(
                output=command_input.output,
                project=command_input.project,
                workspace=choice.target,
            ),
            steps=choice.rerun_steps(steps[choice.source]),
            console=console,
            read_key=read_key,
        )
    return CommandResult(records=forked.records + edited.records, exit_code=edited.exit_code)


def _sources(
    manifest: "ProjectManifest",
) -> "tuple[list[SourceRow], dict[str, list[StepRow]], dict[str, str]]":
    """The project's active workspaces as fork sources, their steps and directories."""
    from chipcompiler.cli.interactive.workspace_fork import SourceRow

    rows: list[SourceRow] = []
    steps: dict[str, list[StepRow]] = {}
    directories: dict[str, str] = {}
    for entry in manifest.active_workspaces():
        directory = entry.workspace_path or os.path.join(manifest.project_dir, entry.workspace_id)
        directories[entry.workspace_id] = directory
        flow = _steps(directory)
        steps[entry.workspace_id] = flow or []
        rows.append(
            SourceRow(
                workspace_id=entry.workspace_id,
                status=entry.status,
                done=sum(step.state == "Success" for step in flow or []),
                total=len(flow or []),
                forked_from=_lineage(entry.raw),
                blocked=_blocked(directory, flow),
            )
        )
    return rows, steps, directories


def _blocked(directory: str, flow: "list[StepRow] | None") -> str | None:
    """Why the workspace in *directory* (with *flow*) cannot be forked, or None."""
    from chipcompiler.engine.snapshot import SNAPSHOT_FILENAME

    if flow is None:
        return "it cannot be opened"
    if not flow:
        return "it has no flow steps"
    if not os.path.isfile(os.path.join(directory, "home", SNAPSHOT_FILENAME)):
        return "it has no Engineering Snapshot"
    return None


def _steps(directory: str) -> "list[StepRow] | None":
    """The steps of the workspace in *directory* and their states, or None when unreadable."""
    from chipcompiler.cli.interactive.workspace_fork import StepRow
    from chipcompiler.data import load_workspace

    try:
        workspace = load_workspace(directory)
        if workspace is None:
            return None
        return [
            StepRow(str(step.get("name", "")), str(step.get("state", "")))
            for step in workspace.flow.steps()
            if step.get("name")
        ]
    except (OSError, ValueError):
        return None


def _lineage(entry: dict) -> str:
    """``source@step`` (or ``source``) a project.json entry was forked from."""
    branch = entry.get("branch_from")
    source = entry.get("source_workspace_id")
    if isinstance(branch, dict) and branch.get("source_workspace_id"):
        step = branch.get("source_step")
        return f"{branch['source_workspace_id']}@{step}" if step else branch["source_workspace_id"]
    return source if isinstance(source, str) else ""


def _taken(manifest: "ProjectManifest", name: str) -> bool:
    return manifest.find_workspace(name) is not None or os.path.exists(
        os.path.join(manifest.project_dir, name)
    )


def _requires_managed_source(ctx: CommandContext) -> CommandResult:
    return CommandResult.err(
        [error_record("workspace_fork_requires_managed_source", reason=ctx.manifest_error)]
    )
