#!/usr/bin/env python

"""Run preparation for manifest/virgin projects and existing workspaces.

Pulled out of the command handler: run-target resolution for manifest and
virgin projects, manifest-backed config assembly, and the existing-run
reconcile wiring. Imported lazily by the run handler, so module-level
imports here must stay cheap (no chipcompiler.data at module level).
"""

import os
import sys
from pathlib import Path

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandResult


def invalid_single_segment_id(run_id: str) -> bool:
    return (
        not run_id
        or os.path.isabs(run_id)
        or "/" in run_id
        or (os.sep != "/" and os.sep in run_id)
        or run_id in (".", "..")
    )


def _find_workspace_entry(manifest, run_id: str | None):
    """The declared workspace for a run id; auto-selects a single active one."""
    if run_id is not None:
        return manifest.find_workspace(run_id)
    active = manifest.active_workspaces()
    return active[0] if len(active) == 1 else None


def resolve_manifest_run_target(command_input, ctx):
    """Resolve (run_dir, run_name, registered, warnings) for virgin/manifest projects.

    Returns a CommandResult error instead when the run cannot start:
    manifest_invalid, workspace_not_declared, or invalid_run_id.
    """
    from chipcompiler.cli.core.records import error_record, warning_record
    from chipcompiler.cli.project.manifest import load_manifest

    project_dir = ctx.project_dir
    cli_run_id = command_input.project.run_id

    if ctx.project_state == "virgin":
        run_name = cli_run_id or "default"
        if invalid_single_segment_id(run_name):
            return CommandResult.err(
                [
                    error_record(
                        "invalid_run_id",
                        run=run_name,
                        reason="run id must be a single path segment inside the project",
                    )
                ]
            )
        return (os.path.join(project_dir, run_name), run_name, False, [])

    if ctx.manifest_error and ctx.manifest_error.startswith("manifest_invalid"):
        return CommandResult.err([error_record("manifest_invalid", reason=ctx.manifest_error)])

    manifest = load_manifest(project_dir)
    match = _find_workspace_entry(manifest, cli_run_id)
    if match is None and cli_run_id is None:
        active = manifest.active_workspaces()
        ids = ", ".join(w.workspace_id for w in active) or "(none)"
        return CommandResult.err(
            [
                error_record(
                    "workspace_not_declared",
                    reason=f"--run-id required; declared workspaces: {ids}",
                )
            ]
        )

    if match is not None:
        return (match.workspace_path, match.workspace_id, True, [])

    if invalid_single_segment_id(cli_run_id):
        return CommandResult.err(
            [
                error_record(
                    "invalid_run_id",
                    run=cli_run_id,
                    reason="run id must be a single path segment inside the project",
                )
            ]
        )
    warnings = [
        warning_record(
            "workspace_not_registered",
            reason=f"workspace {cli_run_id!r} is not declared in project.json; "
            "the GUI will not show it until it is registered",
        )
    ]
    return (os.path.join(project_dir, cli_run_id), cli_run_id, False, warnings)


def manifest_project_config(command_input, ctx):
    """Assemble a ProjectConfig from the manifest for a manifest-mode run.

    Returns (cfg, flow_config) or a CommandResult error. base_design +
    parameter_patch form the base layer; the workspace entry's
    start_step/end_step seed the flow range at creation.
    """
    from chipcompiler.cli.project.config import ProjectConfig
    from chipcompiler.cli.project.manifest import assemble_config, load_manifest

    try:
        manifest = load_manifest(ctx.project_dir)
    except Exception as exc:
        return CommandResult.err(
            [{"kind": "error", "error": "manifest_invalid", "reason": str(exc)}]
        )

    cli_run_id = command_input.project.run_id
    entry = _find_workspace_entry(manifest, cli_run_id)

    assembled = assemble_config(manifest, entry)
    parameters = assembled["parameters"]
    try:
        frequency = float(parameters.get("frequency_max") or 0)
    except (TypeError, ValueError):
        frequency = 0.0

    design_rtl = list(assembled["rtl_list"])
    if not design_rtl and assembled["origin_verilog"]:
        design_rtl = [assembled["origin_verilog"]]

    cfg = ProjectConfig(
        design_name=assembled["design_name"],
        design_top=assembled["top_module"],
        design_rtl=design_rtl,
        design_clock_port=assembled["clock"],
        design_frequency_mhz=frequency,
        pdk_name=assembled["pdk"],
        pdk_root=assembled["pdk_root"],
        flow_preset="rtl2gds",  # inert: flow_config drives the created range
        project_dir=ctx.project_dir,
    )
    cfg.params_overrides = {}
    cfg.manifest_parameters = parameters
    cfg.manifest_driven = True
    cfg.manifest_origin_def = str(manifest.base_design.get("origin_def") or "")

    flow_config = None
    if entry is not None:
        flow_config = {"start_step": entry.start_step, "end_step": entry.end_step}
    return (cfg, flow_config)


def manifest_base_config(ctx):
    """The full assembled manifest base for a hybrid project, or None.

    Includes identity/pdk/rtl fallbacks and the base parameters; the
    workspace-entry layer (parameter_patch, entry flow range) is applied
    separately once the run name resolves.
    """
    if ctx.project_state != "manifest":
        return None
    from chipcompiler.cli.project.manifest import assemble_config, load_manifest

    try:
        manifest = load_manifest(ctx.project_dir)
    except Exception:
        return None
    return assemble_config(manifest, None)


def manifest_entry_layer(ctx, run_name):
    """(parameters, flow_config) from the declared workspace entry.

    Returns the base parameters layered with the entry's parameter_patch
    and the entry's creation-time flow range; (None, None) when no entry
    declares this run.
    """
    if ctx.project_state != "manifest":
        return (None, None)
    from chipcompiler.cli.project.manifest import assemble_config, load_manifest

    try:
        manifest = load_manifest(ctx.project_dir)
    except Exception:
        return (None, None)
    entry = manifest.find_workspace(run_name)
    if entry is None:
        return (None, None)
    assembled = assemble_config(manifest, entry)
    flow_config = {"start_step": entry.start_step, "end_step": entry.end_step}
    return (assembled["parameters"], flow_config)


def run_existing_workspace(
    command_input,
    ctx,
    cfg,
    run_dir: str,
    run_name: str,
    cli_overrides: dict,
    warning_records: list[dict],
    *,
    workspace_registered: bool,
) -> CommandResult:
    """Run against an existing workspace: reconcile target vs persisted flow.

    Extends a proper-prefix target, resumes from the first non-Success step,
    no-ops when everything already succeeded, and fails divergent flows with
    flow_mismatch before any mutation.
    """
    from chipcompiler.cli.core.records import error_record, warning_record

    project = ctx.project
    project_dir = ctx.project_dir

    if cli_overrides:
        return CommandResult.err(
            [
                error_record(
                    "set_requires_fresh_run",
                    run=run_name,
                    workspace=run_dir,
                    reason="--set applies only to fresh runs; use --overwrite or a new --run-id",
                )
            ]
        )

    warnings = list(warning_records)
    if cfg.params_overrides:
        warnings.append(
            warning_record(
                "params_ignored_on_existing_run",
                reason="[params] in ecc.toml apply only to fresh runs; "
                "the workspace reuses its persisted home/ecc.toml",
            )
        )

    from chipcompiler.data import load_workspace

    workspace = load_workspace(run_dir)
    if workspace is None:
        return CommandResult.err(
            [
                error_record(
                    "invalid_workspace",
                    run=run_name,
                    workspace=run_dir,
                )
            ]
        )

    from chipcompiler.engine.reconcile import reconcile_workspace

    if cfg.manifest_driven:
        # Manifest mode: the workspace's own [flow] is the target; the
        # manifest's start/end seeded it at creation and is not consulted.
        target_section = None
    else:
        target_section = {"preset": cfg.flow_preset} if cfg.flow_preset else None

    result = reconcile_workspace(run_dir, target_section)
    if result.outcome == "mismatch":
        reason = result.error or "flow_mismatch"
        if reason.startswith("workspace_config_invalid"):
            return CommandResult.err(
                [
                    error_record(
                        "workspace_config_invalid",
                        run=run_name,
                        workspace=run_dir,
                        reason=reason,
                    )
                ]
            )
        return CommandResult.err(
            [
                error_record(
                    "flow_mismatch",
                    run=run_name,
                    workspace=run_dir,
                    reason="the configured flow diverges from the persisted one",
                    overwrite=disclosure_cmd("ecc run --overwrite", project, ctx.run_id),
                    hint="use --overwrite to wipe the run, or a new --run-id",
                )
            ]
        )

    if not result.persisted:
        # An existing run directory whose flow ledger has no steps cannot be
        # resumed or extended — nothing valid was persisted.
        return CommandResult.err(
            [
                error_record(
                    "invalid_flow_json",
                    run=run_name,
                    workspace=run_dir,
                    reason="the persisted flow has no steps",
                    overwrite=disclosure_cmd("ecc run --overwrite", project, ctx.run_id),
                )
            ]
        )

    from chipcompiler.engine import EngineFlow

    try:
        engine_flow = EngineFlow(workspace=workspace)
        flow_ok = True
        if result.outcome != "no_op":
            # Re-read the ledger: reconcile may have appended suffix steps
            # after load_workspace populated the in-memory copy.
            from chipcompiler.utility import json_read

            flow_data = json_read(workspace.flow.path or Path(run_dir) / "home" / "flow.json")
            executable = {
                step["name"]
                for step in flow_data.get("steps", [])
                if isinstance(step, dict)
                and isinstance(step.get("name"), str)
                and step.get("state") != "Success"
            }
            engine_flow.create_step_workspaces(executable_steps=executable)

            from chipcompiler.cli.rendering.progress import (
                run_flow_with_progress,
                should_enable_run_progress,
            )

            if should_enable_run_progress(ctx, sys.stderr):
                flow_ok = run_flow_with_progress(engine_flow, ctx, project, sys.stderr)
            else:
                flow_ok = engine_flow.run_steps()
    except Exception as exc:
        return CommandResult.err(
            [
                error_record(
                    "flow_failed",
                    run=run_name,
                    workspace=run_dir,
                    reason=str(exc),
                )
            ]
        )

    if workspace_registered:
        from chipcompiler.cli.project.manifest import write_back_workspace_status

        write_back_workspace_status(project_dir, run_name, "success" if flow_ok else "failed")

    record: dict = {
        "run": run_name,
        "status": "success" if flow_ok else "failed",
        "workspace": run_dir,
        "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
    }
    if result.outcome == "no_op":
        record["no_op"] = True
    if result.appended:
        record["appended_steps"] = list(result.appended)
    records = warnings + [record]
    if ctx.project_state == "legacy":
        from chipcompiler.cli.core.records import legacy_layout_hint_record

        records.append(legacy_layout_hint_record(project))
    if not flow_ok:
        return CommandResult.err(records)
    return CommandResult.ok(records)
