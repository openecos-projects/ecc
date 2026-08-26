#!/usr/bin/env python

"""``ecc migrate``: upgrade a legacy runs/ project to the manifest layout.

Moves each ``runs/<id>`` workspace to ``<root>/<id>``, rebases its
home.json pointers, regenerates tool configs, and registers it in a
generated project.json. Explicit and user-confirmed — never a side effect
of another command. Idempotent: a partially migrated project resumes, an
already migrated one is a no-op report. Planning and the exact preview
live in ``migrate_plan.py``.
"""

import logging
import os
import sys

from chipcompiler.cli.project.manifest import find_manifest, load_manifest, update_manifest
from chipcompiler.cli.project.migrate_plan import (
    MigrationEntry,
    MigrationPreview,
    build_migration_preview,
    preview_records,
    render_preview,
)

logger = logging.getLogger(__name__)


def _append_manifest_entries(
    project_dir: str, append_set: tuple[dict, ...], keep_ids: set[str]
) -> bool:
    """Append the planned workspaces to an existing manifest (resume path).

    *append_set* carries the preview's COMPLETE workspace entries, applied
    verbatim (copied only to avoid aliasing), filtered to the successfully
    moved *keep_ids*; dedup against the live document stays inside the
    atomic update."""

    def mutate(document: dict) -> None:
        workspaces = document.setdefault("workspaces", [])
        known = {entry.get("workspace_id") for entry in workspaces if isinstance(entry, dict)}
        for planned in append_set:
            if planned["workspace_id"] not in keep_ids or planned["workspace_id"] in known:
                continue
            workspaces.append(dict(planned))

    return update_manifest(project_dir, mutate)


def execute_migration(project_dir: str, preview: MigrationPreview) -> tuple[list[dict], int]:
    """Run the migration; returns (records, exit_code).

    Executes exactly the precomputed preview: moves from the plan, and the
    preview's manifest document (or append set) restricted to the entries
    that actually moved.
    """
    from chipcompiler.cli.project import migrate_fs
    from chipcompiler.cli.project.manifest import write_manifest_if_absent

    plan = preview.plan
    records: list[dict] = []

    if plan.container_unsafe is not None:
        # A linked or substituted runs/ container is refused before any
        # enumeration, preview content, or move.
        records.append(
            {
                "kind": "error",
                "error": "migration_failed",
                "reason": f"unsafe runs container: {plan.container_unsafe}",
            }
        )
        return records, 1

    if plan.resume and not plan.entries and not plan.collisions and not plan.unsafe:
        records.append(
            {
                "status": "already_migrated",
                "project": project_dir,
                "reason": "project.json exists and runs/ has no workspaces left",
            }
        )
        return records, 0

    for run_id in plan.collisions:
        records.append(
            {
                "kind": "error",
                "error": "migration_collision",
                "run": run_id,
                "reason": f"{run_id} already exists at the project root",
            }
        )

    for run_id in plan.unsafe:
        records.append(
            {
                "kind": "error",
                "error": "migration_failed",
                "run": run_id,
                "reason": "unsafe run source: not a real project-owned directory "
                "(symlink or special entry); remove the link or migrate its target by hand",
            }
        )

    migrated: list[MigrationEntry] = []
    moved_records: list[tuple[MigrationEntry, dict]] = []
    container_fd = None
    project_fd = None
    runs_dir = os.path.join(project_dir, "runs")
    try:
        # Bind the destination: the resolved project directory must
        # still be the confirmed object — a retargeted symlink or a
        # replaced project dir refuses before any move.
        try:
            project_stat = os.lstat(os.path.realpath(project_dir))
            project_identity = (project_stat.st_dev, project_stat.st_ino)
        except OSError:
            project_identity = None
        if project_identity != (plan.project_dev, plan.project_ino):
            records.append(
                {
                    "kind": "error",
                    "error": "migration_failed",
                    "reason": "project directory changed after preview",
                }
            )
            return records, 1
        container_fd, container_identity = migrate_fs.open_container(runs_dir)
        if container_fd is None:
            records.append(
                {
                    "kind": "error",
                    "error": "migration_failed",
                    "reason": f"unsafe runs container: {container_identity}",
                }
            )
            return records, 1
        if container_identity != (plan.container_dev, plan.container_ino):
            records.append(
                {
                    "kind": "error",
                    "error": "migration_failed",
                    "reason": "runs/ container changed after preview",
                }
            )
            return records, 1
        project_fd = os.open(project_dir, os.O_RDONLY | os.O_DIRECTORY)

        for entry in plan.entries:
            failure = migrate_fs._move_workspace(entry, container_fd, project_fd)
            if failure is not None:
                kind, reason = failure
                records.append(
                    {
                        "kind": "error",
                        "error": kind,
                        "run": entry.run_id,
                        "reason": reason,
                    }
                )
                continue
            migrated.append(entry)
            # Success records are deferred until registration completes:
            # a run never shows both "migrated" and "migration_failed".
            moved_records.append(
                (
                    entry,
                    {
                        "status": "migrated",
                        "run": entry.run_id,
                        "from": entry.source,
                        "to": entry.target,
                        "workspace_status": entry.status,
                    },
                )
            )

        # Fail-loud gate before registration: an entry whose moved target
        # no longer matches its confirmed identity is NEVER registered —
        # it is reported for manual inspection instead.
        confirmed: list[MigrationEntry] = []
        for entry in migrated:
            try:
                current = os.lstat(entry.target)
                identical = (current.st_dev, current.st_ino) == (
                    entry.source_dev,
                    entry.source_ino,
                )
            except OSError:
                identical = False
            if identical:
                confirmed.append(entry)
                continue
            records.append(
                {
                    "kind": "error",
                    "error": "migration_failed",
                    "run": entry.run_id,
                    "reason": "the moved workspace was replaced or removed during "
                    f"migration and was NOT registered; inspect {entry.target} manually",
                }
            )
        migrated = confirmed

        if migrated:
            registered = False
            keep_ids = {entry.run_id for entry in migrated}
            if plan.resume:
                # An already-registered ID bound to a DIFFERENT path is a
                # collision, not a silent skip: never report a move as
                # migrated while project.json points that ID elsewhere.
                id_conflicts = []
                existing = load_manifest(project_dir)
                for entry in migrated:
                    declared = existing.find_workspace(entry.run_id)
                    if declared is not None and os.path.realpath(
                        declared.workspace_path
                    ) != os.path.realpath(entry.target):
                        id_conflicts.append(entry.run_id)
                if id_conflicts:
                    records.append(
                        {
                            "kind": "error",
                            "error": "migration_collision",
                            "run": ", ".join(id_conflicts),
                            "reason": "workspace id already registered in project.json "
                            "at a different path",
                        }
                    )
                else:
                    registered = _append_manifest_entries(
                        project_dir, preview.manifest_appends, keep_ids
                    )
                    if not registered:
                        records.append(
                            {
                                "kind": "error",
                                "error": "manifest_update_failed",
                                "reason": "moved workspaces were not registered in project.json",
                            }
                        )
            else:
                # The exact preview document, restricted to the moved subset;
                # workspaces and qor_baseline derive TOGETHER from the
                # successful moves — never a rolled-back entry.
                workspaces = [
                    workspace
                    for workspace in preview.manifest_document["workspaces"]
                    if workspace.get("workspace_id") in keep_ids
                ]
                document = {
                    **preview.manifest_document,
                    "workspaces": workspaces,
                    "qor_baseline": {
                        **preview.manifest_document["qor_baseline"],
                        "workspace_id": workspaces[0]["workspace_id"],
                    },
                }
                written = write_manifest_if_absent(project_dir, document)
                if not written and find_manifest(project_dir) is not None:
                    # Lost the creation race: append the same complete preview
                    # entries to the winning manifest.
                    written = _append_manifest_entries(project_dir, tuple(workspaces), keep_ids)
                registered = written
                if not written:
                    records.append(
                        {
                            "kind": "error",
                            "error": "manifest_update_failed",
                            "reason": "project.json was not written",
                        }
                    )

            if registered:
                confirmed_ids = {entry.run_id for entry in confirmed}
                records.extend(
                    record for entry, record in moved_records if entry.run_id in confirmed_ids
                )
            if not registered:
                # Registration is part of the transaction: without it the moved
                # workspaces would be stranded at the root, invisible to the GUI
                # and reported as "already migrated" on retry. Move the whole
                # unregistered batch back — and say so honestly when a rollback
                # cannot complete without touching unconfirmed objects.
                stranded = [
                    entry.run_id
                    for entry in migrated
                    if not migrate_fs._rollback_workspace(entry, container_fd, project_fd)
                ]
                if stranded:
                    records.append(
                        {
                            "kind": "error",
                            "error": "migration_rollback_incomplete",
                            "reason": "workspaces left at the project root: " + ", ".join(stranded),
                        }
                    )
                else:
                    records.append(
                        {
                            "kind": "error",
                            "error": "migration_rolled_back",
                            "reason": "all moved workspaces were returned to runs/",
                        }
                    )
    finally:
        if container_fd is not None:
            os.close(container_fd)
        if project_fd is not None:
            os.close(project_fd)

    failures = [r for r in records if r.get("kind") == "error"]
    try:
        if not failures and os.path.isdir(runs_dir) and not os.listdir(runs_dir):
            os.rmdir(runs_dir)
    except OSError:
        logger.warning("could not remove empty runs directory: %s", runs_dir)
    return records, 1 if failures else 0


def migrate_project(command_input, ctx):
    """The ``ecc migrate`` handler: plan, disclose, confirm, execute."""
    # The exclusive project lock is taken BEFORE any state read: a second
    # migration never observes the first one's half-finished transaction
    # (moved but not yet registered) — it waits and then sees the
    # completed state (already_migrated).
    from chipcompiler.cli.project import migrate_fs

    with migrate_fs.project_migrate_lock(ctx.project_dir, exclusive=True):
        return _migrate_project_impl(command_input, ctx)


def _migrate_project_impl(command_input, ctx):
    from chipcompiler.cli.core.types import CommandResult
    from chipcompiler.cli.project.manifest import find_manifest, has_legacy_runs_layout

    project_dir = ctx.project_dir
    has_manifest = find_manifest(project_dir) is not None
    has_legacy = has_legacy_runs_layout(project_dir)

    if has_manifest:
        # Validate the existing manifest semantically before reporting any
        # outcome — a malformed winner must fail loud, whether it is about
        # to be resumed into or reported as already migrated.
        from chipcompiler.cli.project.manifest import ManifestError, load_manifest

        try:
            load_manifest(project_dir)
        except ManifestError as exc:
            return CommandResult.err(
                [{"kind": "error", "error": "manifest_invalid", "reason": str(exc)}]
            )

    if has_manifest and not has_legacy:
        return CommandResult.ok(
            [
                {
                    "status": "already_migrated",
                    "project": project_dir,
                    "reason": "project.json exists and runs/ has no workspaces left",
                }
            ]
        )
    if not has_legacy:
        return CommandResult.ok(
            [
                {
                    "status": "nothing_to_migrate",
                    "project": project_dir,
                    "reason": "no runs/ workspaces found",
                }
            ]
        )

    cfg = ctx.config
    if cfg is None and not has_manifest:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "missing_config",
                    "path": os.path.join(project_dir, "ecc.toml"),
                }
            ]
        )

    if cfg is not None and not has_manifest:
        # The generated manifest's base_design comes from this config;
        # semantic errors (broken TOML, bad params, missing identity fields,
        # unknown PDK/preset) must not produce an invalid manifest.
        # Filesystem existence checks stay out of scope: migration does not
        # run the flow.
        problems = list(getattr(cfg, "_param_errors", []))
        problems.extend(getattr(cfg, "_pdk_config_errors", []))
        if getattr(cfg, "_toml_error", None):
            problems.append(f"malformed ecc.toml: {cfg._toml_error}")
        if not cfg.design_name:
            problems.append("design.name is required")
        if not cfg.design_top:
            problems.append("design.top is required")
        if not cfg.design_clock_port:
            problems.append("design.clock_port is required")
        if not cfg.design_rtl:
            problems.append("design.rtl must have at least one entry")
        from chipcompiler.cli.project.config import SUPPORTED_PDK_NAMES

        if not cfg.pdk_name:
            problems.append("pdk.name is required")
        elif cfg.pdk_name not in SUPPORTED_PDK_NAMES:
            problems.append(f"unsupported pdk.name: {cfg.pdk_name}")
        if not cfg.flow_preset:
            problems.append("flow.preset is required")
        else:
            from chipcompiler import rtl2gds as rtl2gds_api

            if cfg.flow_preset not in rtl2gds_api.get_flow_builders():
                problems.append(f"unsupported flow.preset: {cfg.flow_preset}")
        if problems:
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "config_error",
                        "reason": problem,
                    }
                    for problem in problems
                ]
            )

    # One exact preview drives disclosure, confirmation, and execution.
    # --yes suppresses only the confirmation prompt, never the disclosure.
    preview = build_migration_preview(project_dir, cfg)
    plan_records = preview_records(preview)

    if not command_input.yes:
        if not sys.stdin.isatty():
            return CommandResult.err(
                plan_records
                + [
                    {
                        "kind": "error",
                        "error": "confirmation_required",
                        "reason": "re-run with --yes to migrate",
                    }
                ]
            )
        render_preview(preview)
        answer = input("Migrate these workspaces? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "migration_aborted",
                        "reason": "declined by user",
                    }
                ]
            )
    elif sys.stdin.isatty():
        render_preview(preview)

    records, exit_code = execute_migration(project_dir, preview)
    return CommandResult(records=tuple(plan_records + records), exit_code=exit_code)
