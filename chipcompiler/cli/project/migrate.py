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
import sys
from dataclasses import dataclass, field

from chipcompiler.cli.project.manifest import (
    build_manifest_document,
    find_manifest,
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


@dataclass(frozen=True)
class MigrationPlan:
    project_dir: str
    entries: tuple[MigrationEntry, ...]
    collisions: tuple[str, ...] = field(default_factory=tuple)
    resume: bool = False


def _flow_status(steps: list[dict]) -> str:
    states = {str(step.get("state", "")) for step in steps if isinstance(step, dict)}
    if not states:
        return "not_started"
    if states & {"Ongoing", "Pending"}:
        return "in_progress"
    if "Imcomplete" in states:
        return "failed"
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
    """Enumerate the runs/ workspaces to move and any name collisions."""
    runs_dir = os.path.join(project_dir, "runs")
    entries: list[MigrationEntry] = []
    collisions: list[str] = []
    try:
        run_ids = sorted(
            entry
            for entry in os.listdir(runs_dir)
            if os.path.isdir(os.path.join(runs_dir, entry)) and not entry.startswith(".")
        )
    except OSError:
        run_ids = []

    for run_id in run_ids:
        source = os.path.join(runs_dir, run_id)
        target = os.path.join(project_dir, run_id)
        if os.path.lexists(target):
            collisions.append(run_id)
            continue
        steps = _read_flow_steps(source)
        names = [str(step.get("name", "")) for step in steps if isinstance(step, dict)]
        names = [name for name in names if name]
        start = CANONICAL_TO_DISPLAY.get(names[0], "Synth") if names else "Synth"
        end = CANONICAL_TO_DISPLAY.get(names[-1], "Harden") if names else "Harden"
        entries.append(
            MigrationEntry(
                run_id=run_id,
                source=source,
                target=target,
                status=_flow_status(steps),
                start_step=start,
                end_step=end,
            )
        )
    return MigrationPlan(
        project_dir=project_dir,
        entries=tuple(entries),
        collisions=tuple(collisions),
        resume=find_manifest(project_dir) is not None,
    )


def _rebase_home_pointers(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rewrite home.json path values from the old workspace location."""
    home_path = os.path.join(workspace_dir, "home", "home.json")
    with open(home_path, encoding="utf-8") as f:
        data = json.load(f)

    def rebase(value):
        if isinstance(value, str):
            if value.startswith(old_prefix + os.sep) or value == old_prefix:
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


def _rollback_workspace(entry: MigrationEntry) -> None:
    """Undo a failed move: rename back, then restore content at the source.

    The rename alone is not enough — the rebase already rewrote home.json
    pointers (and possibly tool configs) to the target location. Reverse the
    pointer rewrite and regenerate configs from the workspace parameters at
    the original location, best-effort.
    """
    os.rename(entry.target, entry.source)
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


def _move_workspace(entry: MigrationEntry) -> str | None:
    """Move one workspace and rebase it; returns an error string or None.

    A rebase failure rolls the move back and restores the workspace content
    at its original location, all-or-nothing per workspace.
    """
    os.rename(entry.source, entry.target)
    try:
        from chipcompiler.data import load_workspace, refresh_workspace_config

        workspace = load_workspace(entry.target)
        if workspace is None:
            raise ValueError(f"moved workspace fails to load: {entry.target}")
        _rebase_home_pointers(entry.target, entry.source, entry.target)
        workspace = load_workspace(entry.target)
        refresh_workspace_config(workspace)
    except Exception as exc:
        _rollback_workspace(entry)
        return str(exc)
    return None


def _append_manifest_entries(project_dir: str, entries: list[MigrationEntry]) -> bool:
    """Append migrated workspaces to an existing manifest (resume path)."""

    def mutate(document: dict) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        workspaces = document.setdefault("workspaces", [])
        known = {entry.get("workspace_id") for entry in workspaces if isinstance(entry, dict)}
        for entry in entries:
            if entry.run_id in known:
                continue
            workspaces.append(
                {
                    "workspace_id": entry.run_id,
                    "name": document.get("design_name", entry.run_id),
                    "workspace_path": entry.target,
                    "source_workspace_id": None,
                    "branch_from": None,
                    "start_step": entry.start_step,
                    "end_step": entry.end_step,
                    "status": entry.status,
                    "created_at": now,
                    "updated_at": now,
                    "parameter_patch": {},
                    "metrics_summary": {},
                    "step_metrics": {},
                }
            )

    return update_manifest(project_dir, mutate)


def execute_migration(project_dir: str, cfg) -> tuple[list[dict], int]:
    """Run the migration; returns (records, exit_code)."""
    from chipcompiler.cli.project.manifest import write_manifest_if_absent

    plan = plan_migration(project_dir)
    records: list[dict] = []

    if plan.resume and not plan.entries and not plan.collisions:
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

    migrated: list[MigrationEntry] = []
    for entry in plan.entries:
        failure = _move_workspace(entry)
        if failure is not None:
            records.append(
                {
                    "kind": "error",
                    "error": "migration_failed",
                    "run": entry.run_id,
                    "reason": failure,
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
        if plan.resume:
            if not _append_manifest_entries(project_dir, migrated):
                records.append(
                    {
                        "kind": "error",
                        "error": "manifest_update_failed",
                        "reason": "moved workspaces were not registered in project.json",
                    }
                )
        else:
            from chipcompiler.cli.project.config import (
                resolve_pdk_root,
                resolve_rtl,
                to_parameters,
            )

            _, origin_verilog, _ = resolve_rtl(cfg)
            parameters = to_parameters(cfg)
            document = build_manifest_document(
                project_dir,
                design_name=cfg.design_name,
                base_design={
                    "pdk": cfg.pdk_name,
                    "pdk_root": resolve_pdk_root(cfg),
                    "top_module": cfg.design_top,
                    "clock": cfg.design_clock_port,
                    "rtl_list": cfg.design_rtl,
                    "origin_verilog": origin_verilog,
                    "parameters": parameters,
                },
                workspace_id=migrated[0].run_id,
                workspace_path=migrated[0].target,
                start_step=migrated[0].start_step,
                end_step=migrated[0].end_step,
                status=migrated[0].status,
            )
            for extra in migrated[1:]:
                document["workspaces"].append(
                    {
                        **document["workspaces"][0],
                        "workspace_id": extra.run_id,
                        "workspace_path": extra.target,
                        "start_step": extra.start_step,
                        "end_step": extra.end_step,
                        "status": extra.status,
                    }
                )
            written = write_manifest_if_absent(project_dir, document)
            if not written and find_manifest(project_dir) is not None:
                # Lost the creation race: append to the winning manifest.
                written = _append_manifest_entries(project_dir, migrated)
            if not written:
                records.append(
                    {
                        "kind": "error",
                        "error": "manifest_update_failed",
                        "reason": "project.json was not written",
                    }
                )

    runs_dir = os.path.join(project_dir, "runs")
    try:
        if os.path.isdir(runs_dir) and not os.listdir(runs_dir):
            os.rmdir(runs_dir)
    except OSError:
        logger.warning("could not remove empty runs directory: %s", runs_dir)

    failures = [r for r in records if r.get("kind") == "error"]
    return records, 1 if failures else 0


def migrate_project(command_input, ctx):
    """The ``ecc migrate`` handler: plan, confirm, execute."""
    from chipcompiler.cli.core.types import CommandResult
    from chipcompiler.cli.project.manifest import find_manifest, has_legacy_runs_layout

    project_dir = ctx.project_dir
    has_manifest = find_manifest(project_dir) is not None
    has_legacy = has_legacy_runs_layout(project_dir)

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

    if not command_input.yes:
        plan = plan_migration(project_dir)
        planned = [
            {
                "kind": "plan",
                "run": entry.run_id,
                "from": entry.source,
                "to": entry.target,
            }
            for entry in plan.entries
        ]
        if not sys.stdin.isatty():
            return CommandResult.err(
                planned
                + [
                    {
                        "kind": "error",
                        "error": "confirmation_required",
                        "reason": "re-run with --yes to migrate",
                    }
                ]
            )
        for entry in plan.entries:
            print(f"  {entry.source} -> {entry.target}", file=sys.stderr)
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

    records, exit_code = execute_migration(project_dir, cfg)
    return CommandResult(records=tuple(records), exit_code=exit_code)
