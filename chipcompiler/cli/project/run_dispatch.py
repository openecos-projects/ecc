#!/usr/bin/env python

"""Locked run dispatch for project runs.

The run handler resolves config, warnings, and the run target; this
module owns the filesystem decision under the shared project migration
lock: revalidate the project state (a concurrent ``ecc migrate`` can
complete between context construction and here), classify
existing-vs-fresh, refuse or atomically create the run target, and hand
off to preparation/execution. Legacy runs hold the lock through engine
execution — their targets live under ``runs/``, the very paths a
migration moves. Imported lazily by the run handler; keep module-level
imports cheap.
"""

import os
from pathlib import Path

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.run_existing import run_existing_workspace
from chipcompiler.cli.project.run_prepare import execute_fresh_run


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
    home_json = os.path.join(home, "home.json")
    return (
        not os.path.islink(home)
        and not os.path.islink(flow_json)
        and not os.path.islink(home_json)
        and os.path.isfile(flow_json)
    )


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
    """Reject an existing run target that escapes the project.

    A symlinked run target (or one whose home/flow.json is itself linked)
    must never be executed or mutated in place of a project-owned run:
    fail loud instead of touching the external workspace it points at.
    """
    from chipcompiler.cli.core.records import error_record

    if not _resolves_as_spelled(run_dir, project_dir) or not _is_ecc_run_dir(run_dir):
        return CommandResult.err(
            [
                error_record(
                    "run_target_unsafe",
                    workspace_id=run_name,
                    workspace=run_dir,
                    reason="existing target is not an ECC workspace directory inside the project",
                )
            ]
        )
    return None


def _prepare_run_target(command_input, ctx, run_dir: str, run_name: str):
    """Overwrite-delete + atomic create of the run target (the caller holds
    the shared project lock).

    Returns owns_target when the run may proceed, or a CommandResult
    error (overwrite_refused / run_exists). Only the process that
    atomically creates the target may proceed or clean up a failed
    create_workspace: an existing target (pre-existing or won by a
    concurrent run) is never written into or removed by this invocation.
    create_workspace re-attempts the creation, so any other error
    surfaces from there.
    """
    import shutil

    from chipcompiler.cli.core.records import error_record
    from chipcompiler.engine.reconcile import _workspace_lock

    project_dir = ctx.project_dir
    if command_input.overwrite and os.path.lexists(run_dir):
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
        # Serialize the deletion with an active execution of this workspace:
        # flock blocks until the running engine releases the sibling lock
        # (<run_dir>.lock, which survives the rmtree), and the fresh engine
        # re-acquires it on the recreated tree, so two runs never execute
        # against the same paths.
        with _workspace_lock(Path(run_dir)):
            for root, dirs, files in os.walk(run_dir):
                for d in dirs:
                    dp = os.path.join(root, d)
                    if not os.path.islink(dp):
                        os.chmod(dp, 0o755)
                for f in files:
                    fp = os.path.join(root, f)
                    if not os.path.islink(fp):
                        os.chmod(fp, 0o644)
            os.chmod(run_dir, 0o755)
            shutil.rmtree(run_dir)

    try:
        os.makedirs(run_dir)
        return True
    except FileExistsError:
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
    except OSError:
        return False


def _stale_project_state(project_dir: str, expected: str) -> CommandResult | None:
    """Fail-loud guard inside the shared project lock.

    ``build_context`` classifies the project before any lock is held, and
    a concurrent ``ecc migrate`` can complete in that gap. Acting on the
    stale classification would recreate ``runs/<id>`` next to the moved,
    registered ``<root>/<id>`` — so the locked decision revalidates and
    refuses with a retry hint instead of splitting the project.
    """
    from chipcompiler.cli.core.records import error_record
    from chipcompiler.cli.project.manifest import classify_project

    if classify_project(project_dir) == expected:
        return None
    return CommandResult.err(
        [
            error_record(
                "project_state_changed",
                reason="the project layout changed while the run was starting "
                "(a concurrent migration?); retry the command",
            )
        ]
    )


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
) -> CommandResult:
    """Run the existing/fresh decision and target creation under the shared
    project lock, then execute.

    Every filesystem decision derived from the pre-lock context is
    revalidated inside the lock, so an interleaved ``ecc migrate`` either
    waits for this run or turns it into a loud, retryable error — never
    into a recreated ``runs/<id>`` shadowing the migrated workspace.
    """
    from chipcompiler.cli.project import migrate_fs

    def existing_workspace_run() -> CommandResult:
        return run_existing_workspace(
            command_input,
            ctx,
            cfg,
            run_dir,
            run_name,
            cli_overrides,
            warning_records,
            workspace_registered=workspace_registered,
        )

    def fresh_run(*, owns_target: bool) -> CommandResult:
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
        )

    project_dir = ctx.project_dir
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if project_state == "legacy":
        # Legacy runs create inside runs/ — the very paths a migration
        # moves — so state revalidation, the existing/fresh decision,
        # creation, AND the engine all hold the shared project lock.
        with migrate_fs.project_migrate_lock(project_dir, exclusive=False):
            stale = _stale_project_state(project_dir, "legacy")
            if stale is not None:
                return stale
            if os.path.exists(flow_json) and not command_input.overwrite:
                unsafe = _existing_target_guard(run_dir, project_dir, run_name)
                if unsafe is not None:
                    return unsafe
                return existing_workspace_run()
            prepared = _prepare_run_target(command_input, ctx, run_dir, run_name)
            if isinstance(prepared, CommandResult):
                return prepared
            return fresh_run(owns_target=prepared)

    # The overwrite-delete + atomic create run inside the shared project
    # lock: an `ecc migrate` holding the exclusive lock sees them as one
    # serialized section instead of racing the target's appearance. The
    # engine runs outside the lock so a run never holds it for minutes.
    owns_target = False
    with migrate_fs.project_migrate_lock(project_dir, exclusive=False):
        existing = os.path.exists(flow_json) and not command_input.overwrite
        if existing:
            unsafe = _existing_target_guard(run_dir, project_dir, run_name)
            if unsafe is not None:
                return unsafe
        else:
            if not workspace_registered:
                from chipcompiler.cli.core.records import error_record
                from chipcompiler.cli.project.config import resolve_pdk_root
                from chipcompiler.cli.project.manifest import pre_register_workspace

                registration = pre_register_workspace(
                    project_dir,
                    cfg=cfg,
                    pdk_root=resolve_pdk_root(cfg),
                    workspace_id=run_name,
                    workspace_path=run_dir,
                    flow_config=flow_config,
                )
                if registration == "conflict":
                    return CommandResult.err(
                        [
                            error_record(
                                "workspace_conflict",
                                workspace_id=run_name,
                                workspace=run_dir,
                            )
                        ]
                    )
                if registration != "registered":
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
            prepared = _prepare_run_target(command_input, ctx, run_dir, run_name)
            if isinstance(prepared, CommandResult):
                return prepared
            owns_target = prepared
    if existing:
        # Manifest workspaces live outside runs/ — migration never moves
        # them, so the engine must not pin the shared lock for its whole
        # execution the way the legacy branch intentionally does.
        return existing_workspace_run()
    return fresh_run(owns_target=owns_target)
