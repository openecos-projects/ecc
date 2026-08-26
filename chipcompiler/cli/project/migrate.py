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
from pathlib import Path

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


def _contains_symlink(root: str) -> bool:
    """Any symlink anywhere below root (walk never follows links)."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                return True
    return False


def _unsafe_workspace_source(source: str) -> str | None:
    """Why this run source is unsafe to migrate, or None.

    The source and every workspace-local path the migration mutates
    (home/, config/, recursively) must be real, non-symlink filesystem
    objects owned by that workspace.
    """
    if os.path.islink(source) or not os.path.isdir(source):
        return "run source is not a real directory"
    for sub in ("home", "config"):
        sub_path = os.path.join(source, sub)
        if os.path.islink(sub_path):
            return f"{sub} is a symlink"
        if os.path.isdir(sub_path) and _contains_symlink(sub_path):
            return f"{sub} contains a symlink"
    return None


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


def _rebase_home_pointers(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rewrite home.json path values from the old workspace location."""
    home_path = os.path.join(workspace_dir, "home", "home.json")
    with open(home_path, encoding="utf-8") as f:
        data = json.load(f)

    def rebase(value):
        if isinstance(value, str):
            if value == old_prefix or value.startswith(old_prefix + os.sep):
                return new_prefix + value[len(old_prefix) :]
            return value
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebase(item) for item in value]
        return value

    rebased = {key: rebase(value) for key, value in data.items()}
    from chipcompiler.utility import json_write

    if not json_write(home_path, rebased):
        raise OSError(f"failed to write rebased home.json: {home_path}")


def _rename_back_guarded(source: str, target: str, expect_identity: tuple[int, int] | None) -> None:
    """Rename the moved target back, only when safe.

    Never overwrites an object that appeared at the source path. When
    *expect_identity* is given (rollback after rebase), the target is
    moved back only when it is the exact inode this invocation moved;
    when None (immediate revalidation failure), the just-moved target
    itself is moved straight back.
    """
    if os.path.lexists(source):
        logger.warning("move-back skipped: source path reappeared: %s", source)
        return
    if not os.path.lexists(target):
        return
    if expect_identity is not None:
        target_stat = os.lstat(target)
        if (target_stat.st_dev, target_stat.st_ino) != expect_identity:
            logger.warning("move-back skipped: target is not the moved inode: %s", target)
            return
    os.rename(target, source)


def _rollback_workspace(entry: MigrationEntry) -> None:
    """Undo a failed move: rename back, then restore content at the source.

    The rename alone is not enough — the rebase already rewrote home.json
    pointers (and possibly tool configs) to the target location. Reverse the
    pointer rewrite and regenerate configs from the workspace parameters at
    the original location, best-effort. Only the exact inode this invocation
    moved is renamed back, never an object that reappeared at the source.
    """
    _rename_back_guarded(entry.source, entry.target, (entry.source_dev, entry.source_ino))
    try:
        _rebase_home_pointers(entry.source, entry.target, entry.source)
    except (OSError, json.JSONDecodeError):
        logger.warning("rollback: home.json reverse rebase failed for %s", entry.run_id)
    try:
        from chipcompiler.data import load_workspace, refresh_workspace_config

        workspace = load_workspace(entry.source)
        if workspace is not None:
            refresh_workspace_config(workspace)
    except Exception:
        logger.warning("rollback: config regeneration failed for %s", entry.run_id)


def _pre_rebase_legacy_config_paths(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rebase workspace-local pdk config paths BEFORE the moved workspace loads.

    Both the legacy parameters.json ("PDK Config") and an already-migrated
    home/ecc.toml can carry an absolute path under the old location; the
    workspace cannot load while the path points back at the old source.
    """
    legacy_path = Path(workspace_dir) / "home" / "parameters.json"
    if legacy_path.exists():
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        value = data.get("PDK Config")
        if isinstance(value, str) and value.startswith(old_prefix + os.sep):
            data["PDK Config"] = new_prefix + value[len(old_prefix) :]
            legacy_path.write_text(json.dumps(data), encoding="utf-8")

    config_path = Path(workspace_dir) / "home" / "ecc.toml"
    if config_path.exists():
        from chipcompiler.data.parameter import load_parameter, save_parameter

        parameters = load_parameter(config_path)
        value = parameters.data.get("pdk_config")
        if isinstance(value, str) and value.startswith(old_prefix + os.sep):
            parameters.data["pdk_config"] = new_prefix + value[len(old_prefix) :]
            if not save_parameter(parameters):
                raise OSError(f"failed to rebase workspace config paths: {workspace_dir}")


def _move_workspace(
    entry: MigrationEntry, container_identity: tuple[int, int]
) -> tuple[str, str] | None:
    """Move one confirmed workspace and rebase it; (error_kind, reason) or None.

    The container and source must still match their PLAN-TIME identities
    and the target must still not exist immediately before the rename;
    immediately after it, the moved target must match the plan-time
    source identity and stay free of symlink components before any load,
    rebase, or refresh. Every lstat/rename/revalidation sits inside the
    per-workspace failure boundary, and move-backs touch only the exact
    moved inode, never an object that reappeared at the source path.
    """
    try:
        container_stat = os.lstat(os.path.dirname(entry.source))
        if (container_stat.st_dev, container_stat.st_ino) != container_identity:
            return ("migration_failed", "runs/ container changed after preview")
        unsafe_reason = _unsafe_workspace_source(entry.source)
        if unsafe_reason is not None:
            return ("migration_failed", f"unsafe run source: {unsafe_reason}")
        source_stat = os.lstat(entry.source)
        source_identity = (source_stat.st_dev, source_stat.st_ino)
        if source_identity != (entry.source_dev, entry.source_ino):
            return ("migration_failed", "run source changed after preview")
        if os.path.lexists(entry.target):
            return (
                "migration_collision",
                f"{entry.run_id} appeared at the project root after preview",
            )
        os.rename(entry.source, entry.target)
        target_stat = os.lstat(entry.target)
        revalidate_reason = _unsafe_workspace_source(entry.target)
        target_identity = (target_stat.st_dev, target_stat.st_ino)
        if target_identity != source_identity or revalidate_reason is not None:
            # Possible source substitution between preview and move:
            # rename the just-moved object back without load_workspace,
            # rebasing, or refresh — nothing has been written, so there
            # is nothing to restore.
            _rename_back_guarded(entry.source, entry.target, None)
            return (
                "migration_failed",
                "moved target failed revalidation "
                f"({revalidate_reason or 'identity changed after rename'})",
            )
        from chipcompiler.data import load_workspace, refresh_workspace_config

        _pre_rebase_legacy_config_paths(entry.target, entry.source, entry.target)
        workspace = load_workspace(entry.target)
        if workspace is None:
            raise ValueError(f"moved workspace fails to load: {entry.target}")
        _rebase_home_pointers(entry.target, entry.source, entry.target)
        workspace = load_workspace(entry.target)
        refresh_workspace_config(workspace)
    except Exception as exc:
        _rollback_workspace(entry)
        return ("migration_failed", str(exc))
    return None


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
    container_identity = (plan.container_dev, plan.container_ino)
    for entry in plan.entries:
        failure = _move_workspace(entry, container_identity)
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
            registered = _append_manifest_entries(project_dir, preview.manifest_appends, keep_ids)
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
            # unregistered batch back.
            for entry in migrated:
                _rollback_workspace(entry)
            records.append(
                {
                    "kind": "error",
                    "error": "migration_rolled_back",
                    "reason": "all moved workspaces were returned to runs/",
                }
            )

    failures = [r for r in records if r.get("kind") == "error"]
    runs_dir = os.path.join(project_dir, "runs")
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
