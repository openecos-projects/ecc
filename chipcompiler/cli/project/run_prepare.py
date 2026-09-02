#!/usr/bin/env python

"""Run preparation for manifest/virgin projects and fresh workspaces.

Pulled out of the command handler: run-target resolution for manifest and
virgin projects, manifest-backed config assembly, and fresh-run creation
and execution (the existing-run path lives in ``run_existing``). Imported
lazily by the run handler, so module-level imports here must stay cheap
(no chipcompiler.data at module level).
"""

import contextlib
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
        # A configured [flow] run id resolves through ctx.run_id: honoring
        # it keeps the first writer on the same workspace the inspector shows.
        run_name = cli_run_id or ctx.run_id or "default"
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
    # An undeclared id that canonically lands on a DECLARED workspace's
    # path would operate that workspace under an alias the document never
    # spelled — bypassing its registration and status write-back. Refuse
    # and name the declared selector instead.
    candidate_real = os.path.realpath(os.path.join(project_dir, cli_run_id))
    for workspace in manifest.workspaces:
        if os.path.realpath(workspace.workspace_path) == candidate_real:
            return CommandResult.err(
                [
                    error_record(
                        "workspace_not_declared",
                        run=cli_run_id,
                        reason=f"workspace id {cli_run_id!r} is not declared in project.json; "
                        f"the workspace at that path is declared as {workspace.workspace_id!r}",
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
    single-source rule. Entries that are themselves filelists (``.f``) are
    expanded in place — a nested filelist copied verbatim would be fed to
    synthesis as an HDL source, silently dropping everything it names. The
    file is named ``filelist`` so the frozen origin copy is the same name
    ``load_workspace`` restores on reopen (a random temp basename would be
    lost, silently narrowing a resumed workspace to the first RTL source).
    Returns the filelist path.
    """
    import tempfile

    from chipcompiler.cli.project.config import FILELIST_SUFFIXES, _resolve_path
    from chipcompiler.utility.filelist import (
        parse_filelist,
        parse_incdir_directives,
    )
    from chipcompiler.utility.filelist import (
        resolve_path as resolve_filelist_entry,
    )

    temp_dir = tempfile.mkdtemp(prefix="ecc-rtl-")
    filelist_path = os.path.join(temp_dir, "filelist")
    with open(filelist_path, "w", encoding="utf-8") as f:
        for entry in cfg.design_rtl:
            resolved_entry = _resolve_path(cfg.project_dir, entry)
            if os.path.splitext(resolved_entry)[1].lower() in FILELIST_SUFFIXES:
                nested_dir = os.path.dirname(resolved_entry)
                for nested in parse_filelist(resolved_entry):
                    f.write(_quote_filelist_path(resolve_filelist_entry(nested, nested_dir)) + "\n")
                # Keep the nested file's include directives (rebased to
                # absolute): dropping them silently breaks `include sources.
                for incdir in parse_incdir_directives(resolved_entry):
                    f.write(f"+incdir+{resolve_filelist_entry(incdir, nested_dir)}\n")
            else:
                f.write(_quote_filelist_path(resolved_entry) + "\n")
    return filelist_path


def _quote_filelist_path(path: str) -> str:
    """Quote a filelist entry containing whitespace (Slang requires it)."""
    return f'"{path}"' if any(ch.isspace() for ch in path) else path


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
    from chipcompiler.cli.project.config import (
        resolve_pdk_overrides,
        resolve_pdk_root,
        resolve_rtl,
        to_parameters,
    )
    from chipcompiler.data import create_workspace
    from chipcompiler.data.parameter import save_parameter, update_parameters
    from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
    from chipcompiler.engine import EngineFlow

    project = ctx.project
    project_dir = ctx.project_dir

    _, origin_verilog, input_filelist = resolve_rtl(cfg)
    generated_filelist = None
    if len(cfg.design_rtl) > 1:
        # Manifest-backed projects may declare several RTL sources;
        # materialize them as one generated filelist for creation. A failure
        # here must not strand a partial run target for the next run.
        try:
            generated_filelist = _materialize_rtl_filelist(cfg)
        except Exception as exc:
            if owns_target:
                shutil.rmtree(run_dir, ignore_errors=True)
            return _workspace_failed_result(run_name, run_dir, str(exc))
        input_filelist = generated_filelist
        origin_verilog = ""
    parameters = to_parameters(cfg)
    pdk_root = resolve_pdk_root(cfg)

    manifest_parameters = cfg.manifest_parameters
    if manifest_parameters:
        # Manifest base layer: ecc.toml/--set values overlay it, not the
        # other way around. Values were validated up front by
        # effective_config.validate_effective (shared with `ecc check`).
        from chipcompiler.data.parameter_keys import geometry_to_parameters

        base = geometry_to_parameters(manifest_parameters)
        update_parameters(parameters, base)
        parameters = base

    if cfg.params_overrides or cli_overrides:
        from chipcompiler.cli.project.params import (
            build_backend_overrides,
            build_config_overrides,
            build_pdk_overrides,
            resolve_parameters,
        )

        resolved, _ = resolve_parameters(
            toml_overrides=cfg.params_overrides,
            cli_overrides=cli_overrides,
        )
        update_parameters(build_backend_overrides(resolved), parameters)
        config_overrides = build_config_overrides(resolved)
        if config_overrides:
            update_parameters({CONFIG_OVERRIDES_KEY: config_overrides}, parameters)
        pdk_cli_overrides = build_pdk_overrides(resolved)
    else:
        pdk_cli_overrides = {}

    from chipcompiler.cli.project import migrate_fs
    from chipcompiler.engine.reconcile import _workspace_lock

    # Lock order is always migration → workspace, and the workspace lock
    # is taken BEFORE the target becomes discoverable (flow.json appears
    # in create_workspace): a concurrent `ecc run` can never classify
    # this target as existing and win the race to execute it. The lock
    # file lives next to the workspace, so it predates and survives the
    # creation. It stays held through seeding and engine execution below —
    # the same execution ownership as the existing-run path — while the
    # migration lock is released right after creation so a run never pins
    # project-wide migration for minutes.
    ws_locks = contextlib.ExitStack()
    try:
        with migrate_fs.project_migrate_lock(project_dir, exclusive=False):
            ws_locks.enter_context(_workspace_lock(Path(run_dir)))
            try:
                workspace = create_workspace(
                    directory=run_dir,
                    origin_def=cfg.manifest_origin_def,
                    origin_verilog=origin_verilog,
                    pdk=cfg.pdk_name,
                    parameters=parameters,
                    input_filelist=input_filelist,
                    pdk_root=pdk_root,
                    pdk_overrides=resolve_pdk_overrides(cfg, pdk_cli_overrides),
                    flow_config=flow_config,
                )
            except Exception as exc:
                if owns_target:
                    shutil.rmtree(run_dir, ignore_errors=True)
                return _workspace_failed_result(run_name, run_dir, str(exc))
            finally:
                if generated_filelist is not None:
                    with contextlib.suppress(OSError):
                        shutil.rmtree(os.path.dirname(generated_filelist))

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
                # The write was lost to a concurrent creator OR failed: in
                # both cases continue read-only against whatever won — but
                # never silently, because a run the GUI cannot see is not a
                # full success.
                from chipcompiler.cli.core.records import warning_record
                from chipcompiler.cli.project.manifest import load_manifest

                try:
                    winner = load_manifest(project_dir)
                    matched = winner.find_workspace(run_name)
                    # The winner must declare THIS id at THIS path: a
                    # concurrent manifest that reused the id for another
                    # workspace must not receive our run's status.
                    workspace_registered = matched is not None and os.path.realpath(
                        matched.workspace_path
                    ) == os.path.realpath(run_dir)
                except Exception:
                    workspace_registered = False
                if not workspace_registered:
                    warning_records.append(
                        warning_record(
                            "manifest_generation_failed",
                            reason="project.json was not created and no valid manifest "
                            "declares this run; the GUI will not show it",
                        )
                    )

        # Engine execution still holds the workspace lock taken before
        # creation: a second `ecc run` taking the existing-workspace path
        # can never race this ledger or its outputs.
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
                return CommandResult.err(warning_records + failure_records)
        except Exception as exc:
            from chipcompiler.cli.core.records import error_record

            if workspace_registered:
                _write_back_status(project_dir, run_name, "failed", warning_records)
            return CommandResult.err(
                warning_records
                + [error_record("flow_failed", run=run_name, workspace=run_dir, reason=str(exc))]
            )
    finally:
        ws_locks.close()

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
    return CommandResult.ok(warning_records + success_records)
