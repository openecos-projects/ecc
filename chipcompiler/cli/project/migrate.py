#!/usr/bin/env python

"""``ecc migrate``: upgrade a legacy runs/ project to the manifest layout.

Moves each ``runs/<id>`` workspace to ``<root>/<id>``, rebases its
home.json pointers, regenerates tool configs, and registers it in a
generated project.json. Explicit and user-confirmed — never a side effect
of another command. Idempotent: a partially migrated project resumes, an
already migrated one is a no-op report.
"""

import json
import logging
import os
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

from chipcompiler.cli.project.manifest import (
    base_design_from_config,
    build_manifest_document,
    find_manifest,
    load_manifest,
    manifest_workspace_entry,
    update_manifest,
)

logger = logging.getLogger(__name__)

# Canonical step name -> GUI display name (manifest vocabulary).
CANONICAL_TO_DISPLAY = {
    "Synthesis": "Synth",
    "Floorplan": "Floor",
    "fixFanout": "Fanout",
    "place": "Place",
    "CTS": "CTS",
    "legalization": "Legal",
    "route": "Route",
    "drc": "DRC",
    "lvs": "LVS",
    "filler": "Filler",
    "RCX": "RCX",
    "sta": "STA",
    "Harden": "Harden",
}


@dataclass(frozen=True)
class MigrationEntry:
    run_id: str
    source: str
    target: str
    status: str
    start_step: str
    end_step: str
    # Plan-time lstat identity of the confirmed source: a substituted
    # real directory fails the move-time check, not just a symlink.
    source_dev: int = 0
    source_ino: int = 0


@dataclass(frozen=True)
class MigrationPlan:
    project_dir: str
    entries: tuple[MigrationEntry, ...]
    collisions: tuple[str, ...] = field(default_factory=tuple)
    # Symlinked or otherwise not-project-owned run sources: never read,
    # never moved, reported as migration_failed and left under runs/.
    unsafe: tuple[str, ...] = field(default_factory=tuple)
    # Set when the runs/ container itself is a symlink or not a real
    # directory: nothing is enumerated, previewed, or executed.
    container_unsafe: str | None = None
    # Plan-time lstat identity of the confirmed runs/ container.
    container_dev: int = 0
    container_ino: int = 0
    resume: bool = False


@dataclass(frozen=True)
class MigrationPreview:
    """The exact migration plan: moves plus the manifest create document
    (or resume append set), computed before any confirmation or mutation
    so display and execution can never drift."""

    plan: MigrationPlan
    manifest_document: dict = field(default_factory=dict)
    manifest_appends: tuple[dict, ...] = field(default_factory=tuple)


def _flow_status(steps: list[dict]) -> str:
    states = {str(step.get("state", "")) for step in steps if isinstance(step, dict)}
    if not states:
        return "not_started"
    if "Incomplete" in states:
        return "failed"
    if states & {"Ongoing", "Pending"}:
        return "in_progress"
    if states == {"Success"}:
        return "success"
    return "not_started"


def _read_flow_steps(run_dir: str) -> list[dict]:
    flow_path = os.path.join(run_dir, "home", "flow.json")
    try:
        with open(flow_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    steps = data.get("steps", [])
    return steps if isinstance(steps, list) else []


def plan_migration(project_dir: str) -> MigrationPlan:
    """Enumerate the runs/ workspaces to move and any name collisions.

    Discovery never follows symlinks: a linked or non-directory runs/
    container refuses before any enumeration (``container_unsafe``), and
    a symlinked child source lands in ``unsafe`` — its flow.json is never
    read and no manifest entry is ever constructed for it. Confirmed
    objects carry their plan-time lstat identity so a later substitution
    fails the move-time check.
    """
    runs_dir = os.path.join(project_dir, "runs")
    container_unsafe = None
    container_dev = container_ino = 0
    try:
        container_stat = os.lstat(runs_dir)
    except OSError:
        container_stat = None
    if container_stat is not None:
        # Screen the lstat mode itself: no follow-up stat calls, no window
        # for the container to change between probes.
        if stat.S_ISLNK(container_stat.st_mode):
            container_unsafe = "runs/ is a symlink"
        elif not stat.S_ISDIR(container_stat.st_mode):
            container_unsafe = "runs/ is not a directory"
        else:
            container_dev, container_ino = container_stat.st_dev, container_stat.st_ino
    if container_unsafe is not None:
        return MigrationPlan(
            project_dir=project_dir,
            entries=(),
            container_unsafe=container_unsafe,
            resume=find_manifest(project_dir) is not None,
        )

    entries: list[MigrationEntry] = []
    collisions: list[str] = []
    unsafe: list[str] = []
    try:
        with os.scandir(runs_dir) as scan:
            dirents = sorted(scan, key=lambda dirent: dirent.name)
    except OSError:
        dirents = []

    for dirent in dirents:
        run_id = dirent.name
        if run_id.startswith("."):
            continue
        if dirent.is_symlink() or not dirent.is_dir(follow_symlinks=False):
            unsafe.append(run_id)
            continue
        source = os.path.join(runs_dir, run_id)
        target = os.path.join(project_dir, run_id)
        if os.path.lexists(target):
            collisions.append(run_id)
            continue
        steps = _read_flow_steps(source)
        names = [
            name for step in steps if isinstance(step, dict) and (name := str(step.get("name", "")))
        ]
        source_stat = os.lstat(source)
        entries.append(
            MigrationEntry(
                run_id=run_id,
                source=source,
                target=target,
                status=_flow_status(steps),
                start_step=CANONICAL_TO_DISPLAY.get(names[0], "Synth") if names else "Synth",
                end_step=CANONICAL_TO_DISPLAY.get(names[-1], "Harden") if names else "Harden",
                source_dev=source_stat.st_dev,
                source_ino=source_stat.st_ino,
            )
        )
    return MigrationPlan(
        project_dir=project_dir,
        entries=tuple(entries),
        collisions=tuple(collisions),
        unsafe=tuple(unsafe),
        container_dev=container_dev,
        container_ino=container_ino,
        resume=find_manifest(project_dir) is not None,
    )


def _workspace_entries(
    entries: tuple[MigrationEntry, ...], *, name: str, now: str
) -> tuple[dict, ...]:
    """Complete workspace entries for the planned moves (preview-exact:
    the applied objects are these, copied — never a partial reconstruction)."""
    return tuple(
        manifest_workspace_entry(
            entry.run_id,
            name=name,
            workspace_path=entry.target,
            start_step=entry.start_step,
            end_step=entry.end_step,
            status=entry.status,
            now=now,
        )
        for entry in entries
    )


def build_migration_preview(project_dir: str, cfg) -> MigrationPreview:
    """Compute the immutable preview: every move plus the exact manifest
    create document (or resume append set), before confirmation or mutation."""
    plan = plan_migration(project_dir)
    document: dict = {}
    appends: tuple[dict, ...] = ()
    if plan.entries:
        if plan.resume:
            # load_manifest guarantees a non-empty design_name.
            name = load_manifest(project_dir).design_name
            appends = _workspace_entries(plan.entries, name=name, now=datetime.now(UTC).isoformat())
        else:
            from chipcompiler.cli.project.config import resolve_pdk_root

            first = plan.entries[0]
            document = build_manifest_document(
                project_dir,
                design_name=cfg.design_name,
                base_design=base_design_from_config(cfg, resolve_pdk_root(cfg)),
                workspace_id=first.run_id,
                workspace_path=first.target,
                start_step=first.start_step,
                end_step=first.end_step,
                status=first.status,
            )
            document["workspaces"].extend(
                _workspace_entries(
                    plan.entries[1:], name=cfg.design_name, now=document["created_at"]
                )
            )
    return MigrationPreview(plan=plan, manifest_document=document, manifest_appends=appends)


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
    container_fd = None
    project_fd = None
    runs_dir = os.path.join(project_dir, "runs")
    try:
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
            records.append(
                {
                    "status": "migrated",
                    "run": entry.run_id,
                    "from": entry.source,
                    "to": entry.target,
                    "workspace_status": entry.status,
                }
            )

        if migrated:
            registered = False
            keep_ids = {entry.run_id for entry in migrated}
            if plan.resume:
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


def _render_preview(preview: MigrationPreview) -> None:
    """TTY disclosure of the exact plan (stderr): the moves, then the full
    JSON of the manifest document to create (or the append entries)."""
    for entry in preview.plan.entries:
        print(f"  {entry.source} -> {entry.target}", file=sys.stderr)
    if preview.manifest_document:
        print(json.dumps(preview.manifest_document, indent=2), file=sys.stderr)
    elif preview.manifest_appends:
        print(json.dumps(list(preview.manifest_appends), indent=2), file=sys.stderr)


def _preview_records(preview: MigrationPreview) -> list[dict]:
    """The machine-readable disclosure: moves plus the exact manifest action."""
    records: list[dict] = [
        {
            "kind": "plan",
            "run": entry.run_id,
            "from": entry.source,
            "to": entry.target,
        }
        for entry in preview.plan.entries
    ]
    if preview.manifest_document:
        records.append(
            {"kind": "plan", "manifest": "create", "document": preview.manifest_document}
        )
    elif preview.manifest_appends:
        records.append(
            {"kind": "plan", "manifest": "append", "workspaces": list(preview.manifest_appends)}
        )
    return records


def migrate_project(command_input, ctx):
    """The ``ecc migrate`` handler: plan, disclose, confirm, execute."""
    from chipcompiler.cli.core.types import CommandResult
    from chipcompiler.cli.project.manifest import find_manifest, has_legacy_runs_layout

    project_dir = ctx.project_dir
    has_manifest = find_manifest(project_dir) is not None
    has_legacy = has_legacy_runs_layout(project_dir)

    if has_manifest and has_legacy:
        # Resume path: validate the existing manifest semantically before
        # moving anything — a malformed winner must fail before the first
        # rename, not after.
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
    plan_records = _preview_records(preview)

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
        _render_preview(preview)
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
        _render_preview(preview)

    records, exit_code = execute_migration(project_dir, preview)
    return CommandResult(records=tuple(plan_records + records), exit_code=exit_code)
