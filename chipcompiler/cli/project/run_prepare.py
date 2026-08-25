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
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
    )
    from chipcompiler.engine.reconcile import classify_workspace, reconcile_workspace

    def mismatch_error(reason: str) -> CommandResult:
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
        if reason.startswith("flow_adopt_failed"):
            return CommandResult.err(
                [
                    error_record(
                        "flow_adopt_failed",
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

    if cfg.manifest_driven:
        # Manifest mode: the workspace's own [flow] is the target; the
        # manifest's start/end seeded it at creation and is not consulted.
        target_section = None
    else:
        target_section = {"preset": cfg.flow_preset} if cfg.flow_preset else None

    # Pure-read preflight: a divergent flow is rejected BEFORE load_workspace
    # can migrate configs, create home.json/checklist, or take the lock.
    probe = classify_workspace(run_dir, target_section)
    if probe.outcome == "mismatch":
        return mismatch_error(probe.error or "flow_mismatch")

    try:
        workspace = load_workspace(run_dir)
    except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
        return CommandResult.err(
            [
                error_record(
                    "workspace_config_invalid",
                    run=run_name,
                    workspace=run_dir,
                    reason=str(exc),
                )
            ]
        )
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

    result = reconcile_workspace(run_dir, target_section)
    if result.outcome == "mismatch":
        return mismatch_error(result.error or "flow_mismatch")

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
        _write_back_status(project_dir, run_name, "success" if flow_ok else "failed", warnings)

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


def _workspace_failed_result(run_name: str, run_dir: str, reason: str | None) -> CommandResult:
    from chipcompiler.cli.core.records import error_record

    record = error_record("workspace_failed", run=run_name, workspace=run_dir)
    if reason is not None:
        record["reason"] = reason
    return CommandResult.err([record])


def _write_back_status(project_dir: str, run_name: str, status: str, warning_records: list) -> None:
    """Best-effort manifest status write-back; degrades to a warning."""
    from chipcompiler.cli.core.records import warning_record
    from chipcompiler.cli.project.manifest import write_back_workspace_status

    if not write_back_workspace_status(project_dir, run_name, status):
        warning_records.append(
            warning_record(
                "manifest_write_back_failed",
                reason="run status could not be written back to project.json",
            )
        )


def _materialize_rtl_filelist(cfg) -> str:
    """Write the declared multi-entry rtl list as one generated filelist.

    Paths resolve against the project directory, mirroring resolve_rtl's
    single-source rule. Returns the filelist path.
    """
    import tempfile

    from chipcompiler.cli.project.config import _resolve_path

    fd, filelist_path = tempfile.mkstemp(prefix="ecc-rtl-", suffix=".f")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for entry in cfg.design_rtl:
            f.write(_resolve_path(cfg.project_dir, entry) + "\n")
    return filelist_path


def execute_fresh_run(
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
    owns_target: bool,
) -> CommandResult:
    """Create the workspace, seed it, execute the flow, and map the result.

    Fresh-run preparation and execution for a project run: parameter
    assembly, workspace creation, flow target seeding, virgin manifest
    generation, engine execution, and status write-back.
    """
    import shutil

    from chipcompiler import rtl2gds as rtl2gds_api
    from chipcompiler.cli.core.records import legacy_layout_hint_record
    from chipcompiler.cli.project.config import (
        resolve_pdk_overrides,
        resolve_pdk_root,
        resolve_rtl,
        to_parameters,
    )
    from chipcompiler.data import create_workspace
    from chipcompiler.data.parameter import save_parameter, update_parameters
    from chipcompiler.engine import EngineFlow

    project = ctx.project
    project_dir = ctx.project_dir

    _, origin_verilog, input_filelist = resolve_rtl(cfg)
    if len(cfg.design_rtl) > 1:
        # Manifest-backed projects may declare several RTL sources;
        # materialize them as one generated filelist for creation.
        input_filelist = _materialize_rtl_filelist(cfg)
        origin_verilog = ""
    parameters = to_parameters(cfg)
    pdk_root = resolve_pdk_root(cfg)

    manifest_parameters = cfg.manifest_parameters
    if manifest_parameters:
        from chipcompiler.data.parameter_keys import geometry_to_parameters

        # Manifest base layer: ecc.toml/--set values overlay it, not the
        # other way around.
        base = geometry_to_parameters(manifest_parameters)
        update_parameters(parameters, base)
        parameters = base

    if cfg.params_overrides or cli_overrides:
        from chipcompiler.cli.project.params import (
            build_backend_overrides,
            resolve_parameters,
        )

        resolved, _ = resolve_parameters(
            toml_overrides=cfg.params_overrides,
            cli_overrides=cli_overrides,
        )
        update_parameters(build_backend_overrides(resolved), parameters)

    try:
        workspace = create_workspace(
            directory=run_dir,
            origin_def=cfg.manifest_origin_def,
            origin_verilog=origin_verilog,
            pdk=cfg.pdk_name,
            parameters=parameters,
            input_filelist=input_filelist,
            pdk_root=pdk_root,
            pdk_overrides=resolve_pdk_overrides(cfg),
            flow_config=flow_config,
        )
    except Exception as exc:
        if owns_target:
            shutil.rmtree(run_dir, ignore_errors=True)
        return _workspace_failed_result(run_name, run_dir, str(exc))

    if workspace is None:
        if owns_target:
            shutil.rmtree(run_dir, ignore_errors=True)
        return _workspace_failed_result(run_name, run_dir, None)

    if cli_overrides:
        import json

        provenance_path = os.path.join(run_dir, "home", "cli-param-overrides.json")
        os.makedirs(os.path.dirname(provenance_path), exist_ok=True)
        with open(provenance_path, "w") as _f:
            json.dump(cli_overrides, _f)

    if flow_config is None:
        # CLI-born workspaces persist the named prefix chain as their target.
        workspace_parameters = getattr(workspace, "parameters", None)
        if workspace_parameters is not None:
            workspace_parameters.data["_flow"] = {"preset": cfg.flow_preset}
            save_parameter(workspace_parameters)

    if project_state == "virgin":
        from chipcompiler.cli.project.manifest import (
            PRESET_MANIFEST_RANGE,
            base_design_from_config,
            build_manifest_document,
            write_manifest_if_absent,
        )

        start_step, end_step = PRESET_MANIFEST_RANGE.get(cfg.flow_preset, ("Synth", "Harden"))
        # base_design reflects the ecc.toml-resolved config only; --set
        # values are run-scoped and never baked into the manifest.
        document = build_manifest_document(
            project_dir,
            design_name=cfg.design_name,
            base_design=base_design_from_config(cfg, pdk_root),
            workspace_id=run_name,
            workspace_path=run_dir,
            start_step=start_step,
            end_step=end_step,
        )
        if write_manifest_if_absent(project_dir, document):
            workspace_registered = True
        else:
            # Lost the generation race: discard ours, reload the winner, and
            # continue read-only — write-back applies only when the winning
            # manifest actually declares this workspace.
            from chipcompiler.cli.project.manifest import load_manifest

            try:
                winner = load_manifest(project_dir)
                workspace_registered = winner.find_workspace(run_name) is not None
            except Exception:
                workspace_registered = False

    try:
        engine_flow = EngineFlow(workspace=workspace)
        flow_builders = rtl2gds_api.get_flow_builders()
        if not engine_flow.has_init():
            for step, tool, state in flow_builders[cfg.flow_preset]():
                engine_flow.add_step(step=step, tool=tool, state=state)

        engine_flow.create_step_workspaces()

        from chipcompiler.cli.rendering.progress import (
            run_flow_with_progress,
            should_enable_run_progress,
        )

        if should_enable_run_progress(ctx, sys.stderr):
            flow_ok = run_flow_with_progress(engine_flow, ctx, project, sys.stderr)
        else:
            flow_ok = engine_flow.run_steps()

        if not flow_ok:
            if workspace_registered:
                _write_back_status(project_dir, run_name, "failed", warning_records)
            failure_records = [
                {
                    "run": run_name,
                    "status": "failed",
                    "workspace": run_dir,
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                    "log": disclosure_cmd("ecc log", project, ctx.run_id),
                }
            ]
            if ctx.project_state == "legacy":
                failure_records.append(legacy_layout_hint_record(project))
            return CommandResult.err(warning_records + failure_records)
    except Exception as exc:
        from chipcompiler.cli.core.records import error_record

        return CommandResult.err(
            [error_record("flow_failed", run=run_name, workspace=run_dir, reason=str(exc))]
        )

    if workspace_registered:
        _write_back_status(project_dir, run_name, "success", warning_records)

    success_records = [
        {
            "run": run_name,
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
        }
    ]
    if project_state == "legacy":
        success_records.append(legacy_layout_hint_record(project))
    return CommandResult.ok(warning_records + success_records)
