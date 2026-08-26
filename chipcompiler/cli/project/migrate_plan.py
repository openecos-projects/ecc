#!/usr/bin/env python

"""Planning and preview for ``ecc migrate``.

Pure discovery over the legacy ``runs/`` layout: enumerate the workspaces
to move (never following symlinks), bind every confirmed object's
plan-time lstat identity, and compute the exact manifest document (or
resume append set) before any confirmation or mutation — disclosure and
execution can never drift. Execution lives in ``migrate.py``.
"""

import json
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
)

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
    # Plan-time lstat identity of the RESOLVED project directory: a
    # retargeted project symlink or replaced project dir fails at
    # execution time before any move.
    project_dev: int = 0
    project_ino: int = 0
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
    if states & {"Incomplete", "Invalid"}:
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
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        # JSON-valid but not an object: unreadable as a flow ledger,
        # degrade to the empty-ledger defaults instead of crashing.
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
    project_identity = (0, 0)
    try:
        project_stat = os.lstat(os.path.realpath(project_dir))
        project_identity = (project_stat.st_dev, project_stat.st_ino)
    except OSError:
        pass
    return MigrationPlan(
        project_dir=project_dir,
        entries=tuple(entries),
        collisions=tuple(collisions),
        unsafe=tuple(unsafe),
        container_dev=container_dev,
        container_ino=container_ino,
        project_dev=project_identity[0],
        project_ino=project_identity[1],
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


def render_preview(preview: MigrationPreview) -> None:
    """TTY disclosure of the exact plan (stderr): the moves, then the full
    JSON of the manifest document to create (or the append entries)."""
    for entry in preview.plan.entries:
        print(f"  {entry.source} -> {entry.target}", file=sys.stderr)
    if preview.manifest_document:
        print(json.dumps(preview.manifest_document, indent=2), file=sys.stderr)
    elif preview.manifest_appends:
        print(json.dumps(list(preview.manifest_appends), indent=2), file=sys.stderr)


def preview_records(preview: MigrationPreview) -> list[dict]:
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
