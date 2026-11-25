#!/usr/bin/env python

"""Run dispatch for project runs.

The run handler resolves config, warnings, and the run target. This module
classifies existing-vs-fresh, refuses or atomically creates the run target,
and hands off to preparation/execution. Imported lazily by the run handler; keep module-level
imports cheap.
"""

import contextlib
import os
from pathlib import Path

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.creation import existing_draft_workspace, repeats_recorded_create
from chipcompiler.cli.project.run_existing import run_existing_workspace
from chipcompiler.cli.project.run_prepare import execute_fresh_run
from chipcompiler.project.manifest import MANIFEST_FILENAME


def _is_ecc_run_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        if not os.listdir(path):
            return True
    except OSError:
        return False
    home = os.path.join(path, "home")
    flow_json = os.path.join(home, "flow.json")
    return not os.path.islink(home) and not os.path.islink(flow_json) and os.path.isfile(flow_json)


def _resolves_as_spelled(path: str, anchor: str) -> bool:
    """Return True when path canonically resolves where its spelling claims.

    For a path spelled inside anchor, the canonical resolution must equal the
    anchor's canonical resolution plus the textual tail; for any other path
    (external or escaping), the canonical resolution must equal the
    normalized spelling. A symlink component that redirects the target —
    including one hidden behind ".." segments, which os.path.normpath would
    collapse textually — breaks the equality. The anchor itself is trusted,
    so a project reached through a symlinked parent keeps working.
    """
    spelled = os.path.normpath(path)
    base = os.path.normpath(anchor)
    if spelled == base:
        return os.path.realpath(path) == os.path.realpath(base)
    if spelled.startswith(base + os.sep):
        tail = spelled[len(base) + 1 :]
        return os.path.realpath(path) == os.path.join(os.path.realpath(base), tail)
    return os.path.realpath(path) == spelled


def _existing_target_guard(run_dir: str, project_dir: str, run_name: str) -> CommandResult | None:
    """Reject an existing run target that is linked or malformed.

    External workspaces are valid, but their resolved path must match the
    supplied spelling and their metadata boundary must not use symlinks.
    """
    from chipcompiler.cli.core.records import error_record

    if not _resolves_as_spelled(run_dir, project_dir) or not _is_ecc_run_dir(run_dir):
        return CommandResult.err(
            [
                error_record(
                    "run_target_unsafe",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason="existing target is not a canonical ECC workspace directory",
                )
            ]
        )
    return None


def _prepare_run_target(command_input, ctx, run_dir: str, run_name: str, ws_locks):
    """Overwrite-backup + atomic create of the run target (the caller holds
    the shared project lock).

    Enters the sibling workspace lock into *ws_locks* BEFORE the rename and
    leaves it held: the caller keeps it through the replacement's
    construction, so two concurrent overwrite runs serialize end-to-end and
    one's failure cleanup can never destroy the other's completed
    workspace.

    Returns (owns_target, backup_path) when the run may proceed, or a
    CommandResult error (overwrite_refused / run_exists). Only the process
    that atomically creates the target may proceed, restore a backup, or
    clean up a failed create_workspace: an existing target (pre-existing or
    won by a concurrent run) is never written into or removed by this
    invocation. The previous workspace is renamed to a sibling backup
    instead of deleted, so a failed creation can put it back; the backup is
    discarded once the replacement is fully constructed.
    """
    from chipcompiler.utility.workspace_lock import workspace_lock

    project_dir = ctx.project_dir
    backup_path = None
    empty_target = False
    if os.path.isdir(run_dir) and not os.path.islink(run_dir):
        try:
            empty_target = not os.listdir(run_dir)
        except OSError:
            empty_target = False
    use_existing_empty_target = ctx.workspace_path_explicit and empty_target
    if (command_input.overwrite or use_existing_empty_target) and os.path.lexists(run_dir):
        if not _resolves_as_spelled(run_dir, project_dir) or not _is_ecc_run_dir(run_dir):
            return CommandResult.err(
                [
                    error_record(
                        "overwrite_refused",
                        workspace_id=run_name,
                        workspace=run_dir,
                        reason="target is not an ECC workspace directory",
                    )
                ]
            )
        # Serialize the rename with an active execution of this workspace:
        # flock blocks until the running engine releases the sibling lock
        # (<run_dir>.lock, which survives the rename), and the fresh engine
        # re-acquires it on the recreated tree, so two runs never execute
        # against the same paths. The lock stays entered in *ws_locks* until
        # the replacement is built.
        ws_locks.enter_context(workspace_lock(Path(run_dir), blocking=not command_input.no_wait))
        from chipcompiler.cli.project.draft import require_draft_published
        from chipcompiler.cli.project.revision import expected_revision_error

        try:
            require_draft_published(Path(project_dir), Path(run_dir))
        except OSError as exc:
            return CommandResult.err([error_record("workspace_draft_pending", reason=str(exc))])

        conflict = expected_revision_error(
            run_dir,
            command_input.expected_revision,
            workspace_id=run_name,
        )
        if conflict is not None:
            return conflict
        if command_input.run_id:
            from chipcompiler.cli.project.run_process import runtime_process_error_result
            from chipcompiler.project.runtime_processes import (
                RuntimeProcessError,
                require_unused_run_id,
            )

            try:
                require_unused_run_id(run_dir, command_input.run_id)
            except RuntimeProcessError as exc:
                return runtime_process_error_result(exc, workspace_id=run_name, workspace=run_dir)
        backup_path = f"{run_dir}.overwritten-{os.getpid()}"
        # An atomic rename, not a delete: until the replacement is fully
        # constructed the old tree stays on disk and recoverable.
        os.replace(run_dir, backup_path)

    # Every fresh run holds the workspace lock from before the target is
    # created through engine execution (see execute_fresh_run): a live run
    # must hold the sibling lock, or `ecc process inspect` reports it dead
    # and project reconcile flags it as an inconsistent runtime process.
    # The overwrite branch entered the lock above the rename; entering it
    # again here is a same-thread reentrant no-op.
    ws_locks.enter_context(workspace_lock(Path(run_dir), blocking=not command_input.no_wait))

    if command_input.expected_revision is not None and not os.path.lexists(run_dir):
        from chipcompiler.cli.project.revision import expected_revision_error

        conflict = expected_revision_error(
            run_dir,
            command_input.expected_revision,
            workspace_id=run_name,
        )
        if conflict is not None:
            return conflict
    try:
        os.makedirs(run_dir)
        return True, backup_path
    except FileExistsError:
        if backup_path is not None:
            os.replace(backup_path, run_dir)
        return CommandResult.err(
            [
                error_record(
                    "run_exists",
                    workspace_id=run_name,
                    workspace=run_dir,
                    overwrite=disclosure_cmd("ecc run --overwrite", ctx.project, ctx.run_id),
                )
            ]
        )
    except OSError as exc:
        if backup_path is not None:
            with contextlib.suppress(OSError):
                os.replace(backup_path, run_dir)
        return CommandResult.err(
            [
                error_record(
                    "workspace_create_failed",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason=str(exc),
                )
            ]
        )


def _abandon_prepared_target(backup_path: str | None, run_dir: str, *, owns_target: bool) -> None:
    """Undo a prepared-but-unregistered target: remove the empty directory
    and put a renamed-aside previous workspace back."""
    import shutil

    if not owns_target:
        return
    shutil.rmtree(run_dir, ignore_errors=True)
    if backup_path is not None:
        with contextlib.suppress(OSError):
            os.replace(backup_path, run_dir)


def dispatch_project_run(
    command_input,
    ctx,
    cfg,
    run_dir: str,
    run_name: str,
    cli_overrides: dict,
    flow_config,
    project_state: str | None,
    warning_records: list[dict],
    *,
    workspace_registered: bool,
    execute_flow: bool = True,
    draft=None,
) -> CommandResult:
    """Serialize target creation/replacement with workspace locks, then execute."""

    def rejected_create_overrides() -> CommandResult | None:
        """`workspace create --set` on an existing workspace is refused.

        Same rule as `ecc run --set`: an override is recorded when the
        workspace is created, never dropped without a message. A retry of the
        command that created it is not a new request.
        """
        if execute_flow or not cli_overrides:
            return None
        if repeats_recorded_create(command_input, run_dir, run_name):
            return None
        from chipcompiler.cli.core.records import error_record

        return CommandResult.err(
            [
                error_record(
                    "set_requires_fresh_run",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason=(
                        "--set applies only when the workspace is created; "
                        "use ecc param set --workspace or a new workspace id"
                    ),
                )
            ]
        )

    def existing_workspace_run() -> CommandResult:
        # When execute_flow is False (e.g., workspace create on existing target),
        # return success without resuming the flow (#393).
        if not execute_flow:
            rejected = rejected_create_overrides()
            if rejected is not None:
                return rejected
            return CommandResult.ok(
                warning_records
                + [
                    {
                        "workspace_id": run_name,
                        "status": "refreshed",
                        "workspace": run_dir,
                        "run": disclosure_cmd("ecc run", ctx.project, run_name),
                    }
                ]
            )
        return run_existing_workspace(
            command_input,
            ctx,
            cfg,
            run_dir,
            run_name,
            cli_overrides,
            warning_records,
            flow_config=flow_config,
            workspace_registered=workspace_registered,
        )

    def fresh_run(
        *,
        owns_target: bool,
        backup_path: str | None = None,
        ws_locks=None,
        registration_created: bool = False,
    ) -> CommandResult:
        return execute_fresh_run(
            command_input,
            ctx,
            cfg,
            run_dir,
            run_name,
            cli_overrides,
            flow_config,
            project_state,
            warning_records,
            workspace_registered=workspace_registered,
            owns_target=owns_target,
            backup_path=backup_path,
            ws_locks=ws_locks,
            registration_created=registration_created,
            execute_flow=execute_flow,
            draft=draft,
        )

    project_dir = ctx.project_dir
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if execute_flow:
        # A fresh run registers its process only after the workspace exists,
        # so the run identity is checked before anything is created (#431).
        from chipcompiler.cli.project.run_process import run_identity_error

        rejected = run_identity_error(command_input, workspace_id=run_name, workspace=run_dir)
        if rejected is not None:
            return rejected

    # The workspace lock taken for an overwrite rename or creation stays held
    # until the replacement is fully built: one run's failure cleanup cannot
    # destroy another run's completed workspace.
    owns_target = False
    backup_path = None
    created_registration = False
    ws_locks = contextlib.ExitStack()
    try:
        if draft is not None:
            from chipcompiler.utility.workspace_lock import workspace_lock

            target = Path(run_dir)
            blocking = not command_input.no_wait
            ws_locks.enter_context(workspace_lock(target, blocking=blocking))
            if (target / "home" / "flow.json").is_file():
                return existing_draft_workspace(
                    command_input, ctx, run_dir, run_name, preview=False
                )
            try:
                with draft.build_target(
                    target, reuse_empty=ctx.workspace_path_explicit, blocking=blocking
                ):
                    return fresh_run(owns_target=False, ws_locks=ws_locks)
            except BlockingIOError:
                raise
            except OSError as exc:
                code = "run_exists" if isinstance(exc, FileExistsError) else "workspace_failed"
                return CommandResult.err(
                    [error_record(code, workspace_id=run_name, workspace=run_dir, reason=str(exc))]
                )

        existing = os.path.exists(flow_json) and not command_input.overwrite
        if existing:
            unsafe = _existing_target_guard(run_dir, project_dir, run_name)
            if unsafe is not None:
                return unsafe
            # A workspace directory that is there but not declared - an
            # external path, or one kept by a default `workspace delete` -
            # is registered before it is used: neither `ecc run` nor
            # `workspace create` reports success for a workspace the
            # project does not know.
            if not workspace_registered and (
                ctx.workspace_path_explicit or project_state == "manifest"
            ):
                # A command this branch is going to refuse registers nothing.
                rejected = rejected_create_overrides()
                if rejected is None and execute_flow and cli_overrides:
                    from chipcompiler.cli.project.run_existing import rejected_run_overrides

                    rejected = rejected_run_overrides(run_name, run_dir)
                if rejected is not None:
                    return rejected
                from chipcompiler.cli.project.config import resolve_pdk_root
                from chipcompiler.cli.project.workspace_registration import (
                    WorkspaceRegistrationError,
                    register_existing_workspace,
                )

                try:
                    registration, _metadata = register_existing_workspace(
                        project_dir,
                        cfg=cfg,
                        pdk_root=resolve_pdk_root(cfg),
                        workspace_id=run_name,
                        workspace_path=run_dir,
                        blocking=not command_input.no_wait,
                    )
                except BlockingIOError:
                    return CommandResult.err([error_record("workspace_busy")], exit_code=20)
                except WorkspaceRegistrationError as exc:
                    return CommandResult.err(
                        [
                            error_record(
                                exc.code,
                                workspace_id=run_name,
                                workspace=run_dir,
                                reason=str(exc),
                            )
                        ]
                    )
                if registration.startswith("conflict"):
                    return CommandResult.err(
                        [
                            error_record(
                                "workspace_conflict",
                                workspace_id=run_name,
                                workspace=run_dir,
                            )
                        ]
                    )
                if registration not in ("registered", "existing"):
                    return CommandResult.err(
                        [
                            error_record(
                                "workspace_registration_failed",
                                workspace_id=run_name,
                                workspace=run_dir,
                            )
                        ]
                    )
                workspace_registered = True
                # This execution must use the imported workspace's own
                # persisted range, not the project's fresh-run preset - unless
                # the command names a preset, which is checked against it.
                if command_input.preset is None:
                    cfg.manifest_driven = True
        else:
            prepared = _prepare_run_target(command_input, ctx, run_dir, run_name, ws_locks)
            if isinstance(prepared, CommandResult):
                return prepared
            owns_target, backup_path = prepared
            # A direct CLI `ecc run` creates the initial project manifest
            # before execution. Explicit GUI
            # Workspace creation always runs after `ecc init`, so it
            # publishes the directory first and registers it in the
            # fresh-run commit path.
            if not workspace_registered and not os.path.lexists(
                os.path.join(project_dir, MANIFEST_FILENAME)
            ):
                from chipcompiler.cli.project.config import resolve_pdk_root
                from chipcompiler.project.manifest_write import pre_register_workspace

                registration = pre_register_workspace(
                    project_dir,
                    cfg=cfg,
                    pdk_root=resolve_pdk_root(cfg),
                    workspace_id=run_name,
                    workspace_path=run_dir,
                    flow_config=flow_config,
                )
                if registration.startswith("conflict"):
                    _abandon_prepared_target(backup_path, run_dir, owns_target=owns_target)
                    return CommandResult.err(
                        [
                            error_record(
                                "workspace_conflict",
                                workspace_id=run_name,
                                workspace=run_dir,
                            )
                        ]
                    )
                if registration not in ("registered", "existing"):
                    _abandon_prepared_target(backup_path, run_dir, owns_target=owns_target)
                    return CommandResult.err(
                        [
                            error_record(
                                "workspace_registration_failed",
                                workspace_id=run_name,
                                workspace=run_dir,
                            )
                        ]
                    )
                workspace_registered = True
                created_registration = registration == "registered"
        if existing:
            # The engine must not pin the workspace lock for its whole execution.
            return existing_workspace_run()
        return fresh_run(
            owns_target=owns_target,
            backup_path=backup_path,
            ws_locks=ws_locks,
            registration_created=created_registration,
        )
    finally:
        ws_locks.close()
