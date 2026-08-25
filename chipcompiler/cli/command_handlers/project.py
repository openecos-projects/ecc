import contextlib
import os
import shlex
import shutil
import sys

from chipcompiler.cli.core.inputs import CheckInput, InitInput, MigrateInput, RunInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def init(command_input: InitInput, ctx: CommandContext) -> CommandResult:
    name = command_input.name
    if not name or not name.strip():
        return CommandResult.err([{"kind": "error", "error": "project name is required"}])

    project_dir = os.path.abspath(name)
    config_path = os.path.join(project_dir, "ecc.toml")
    design_name = os.path.basename(project_dir)

    if os.path.isfile(project_dir):
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "path_is_file",
                    "path": project_dir,
                }
            ]
        )

    if os.path.exists(config_path):
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "already_exists",
                    "path": config_path,
                }
            ]
        )

    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "rtl"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "constraints"), exist_ok=True)

    default_toml = """[design]
name = "{name}"
top = "{name}"
rtl = ["rtl/{name}.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = ""

[flow]
# preset: rtl2gds | rcx | harden | syn_sta
preset = "rtl2gds"
run = "default"
"""

    with open(config_path, "w") as f:
        f.write(default_toml.format(name=design_name))

    project_arg = ctx.project or name
    return CommandResult.ok(
        [
            {
                "project": name,
                "status": "created",
                "path": name,
                "check": disclosure_cmd("ecc check", project_arg),
                "run": disclosure_cmd("ecc run", project_arg),
            }
        ]
    )


def _check_manifest_project(ctx: CommandContext) -> CommandResult:
    """`ecc check` for a project.json project (no ecc.toml)."""
    project = ctx.project
    if ctx.manifest_error and ctx.manifest_error.startswith("manifest_invalid"):
        return CommandResult.err(
            [
                error_record(
                    "manifest_invalid",
                    reason=ctx.manifest_error,
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    from chipcompiler.cli.project.manifest import load_manifest

    try:
        manifest = load_manifest(ctx.project_dir)
    except Exception as exc:
        return CommandResult.err(
            [
                error_record(
                    "manifest_invalid",
                    reason=str(exc),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    run_dir_display = ctx.run_dir
    if _canonically_inside(ctx.run_dir, ctx.project_dir):
        with contextlib.suppress(ValueError):
            run_dir_display = os.path.relpath(
                os.path.realpath(ctx.run_dir), os.path.realpath(ctx.project_dir)
            )

    records = [
        {
            "project": manifest.design_name,
            "status": "checked",
            "config": "project.json",
            "run_dir": run_dir_display,
            "run": disclosure_cmd("ecc run", project),
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        }
    ]
    if ctx.manifest_error:
        # Read-only intent: an unresolvable run selector is an error, not a
        # warning (the check result above would otherwise look authoritative).
        return CommandResult.err(
            [
                error_record(
                    "workspace_not_declared",
                    reason=ctx.manifest_error,
                )
            ]
        )
    return CommandResult.ok(records)


def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.config import validate_project_config

    project = ctx.project

    cfg = ctx.config
    if cfg is None:
        if ctx.project_state == "manifest":
            return _check_manifest_project(ctx)
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    errors = validate_project_config(cfg)

    if errors:
        return CommandResult.err(
            [
                {
                    "check": "config",
                    "status": "fail",
                    "reason": err,
                    "source": "ecc.toml",
                    "inspect": disclosure_cmd("ecc check --json", project),
                }
                for err in errors
            ]
        )

    run_dir_display = "runs/default"
    if ctx.run_id is not None:
        run_dir_display = ctx.run_dir
        if _canonically_inside(ctx.run_dir, ctx.project_dir):
            with contextlib.suppress(ValueError):
                run_dir_display = os.path.relpath(
                    os.path.realpath(ctx.run_dir), os.path.realpath(ctx.project_dir)
                )

    records = [
        {
            "project": cfg.design_name,
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": run_dir_display,
            "run": disclosure_cmd("ecc run", project),
            "inspect_cmd": disclosure_cmd("ecc status", project),
        }
    ]

    if cfg.design_rtl:
        records.append(
            {
                "check": "rtl",
                "status": "pass",
                "path": cfg.design_rtl[0],
                "inspect": disclosure_cmd("ecc check --json", project),
            }
        )

    if ctx.project_state == "legacy":
        from chipcompiler.cli.core.records import legacy_layout_hint_record

        records.append(legacy_layout_hint_record(project))

    return CommandResult.ok(records)


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


def _canonically_inside(path: str, anchor: str) -> bool:
    """Return True when path's canonical resolution is anchor or below it."""
    real_base = os.path.realpath(anchor)
    real = os.path.realpath(path)
    return real == real_base or real.startswith(real_base.rstrip(os.sep) + os.sep)


def migrate(command_input: MigrateInput, ctx: CommandContext) -> CommandResult:
    """Upgrade a legacy runs/ project to the manifest layout."""
    from chipcompiler.cli.project.migrate import migrate_project

    return migrate_project(command_input, ctx)


def run(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    if command_input.workspace is not None:
        return _run_workspace(command_input, ctx)

    if any(
        (
            command_input.resume,
            command_input.from_step is not None,
            command_input.only is not None,
            command_input.force,
        )
    ):
        return CommandResult.err([{"kind": "error", "error": "selector_requires_workspace"}])

    from chipcompiler import rtl2gds as rtl2gds_api
    from chipcompiler.cli.project import run_prepare
    from chipcompiler.cli.project.config import (
        resolve_pdk_overrides,
        resolve_pdk_root,
        resolve_rtl,
        to_parameters,
        validate_project_config,
    )
    from chipcompiler.data import create_workspace
    from chipcompiler.engine import EngineFlow

    project = ctx.project
    project_dir = ctx.project_dir

    cfg = ctx.config
    flow_config = None
    if cfg is None:
        if ctx.project_state == "manifest":
            assembled = run_prepare.manifest_project_config(command_input, ctx)
            if isinstance(assembled, CommandResult):
                return assembled
            cfg, flow_config = assembled
        else:
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "missing_config",
                        "path": os.path.join(project_dir, "ecc.toml"),
                    }
                ]
            )
    errors = validate_project_config(cfg)
    if errors:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "config_error",
                    "reason": err,
                }
                for err in errors
            ]
        )

    cli_overrides = {}
    raw_sets = command_input.param_set
    if raw_sets:
        from chipcompiler.cli.project.params import parse_cli_overrides

        cli_overrides, set_errors = parse_cli_overrides(raw_sets)
        if set_errors:
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "invalid_parameter",
                        "reason": err,
                    }
                    for err in set_errors
                ]
            )

    # TODO: Move non-interactive project run preparation/execution into
    # chipcompiler.runtime.project_runner.run_project or
    # chipcompiler.engine.project_run.prepare_and_run. Keep CLI ownership limited
    # to input parsing, progress renderer selection, and CommandResult mapping.
    project_state = ctx.project_state
    warning_records: list[dict] = []
    run_dir = ctx.run_dir
    run_name = ctx.run_id or "default"
    workspace_registered = False

    if project_state in ("virgin", "manifest"):
        resolved = run_prepare.resolve_manifest_run_target(command_input, ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        run_dir, run_name, workspace_registered, warning_records = resolved

    if project_state == "manifest" and not cfg.manifest_driven:
        # Hybrid project (both ecc.toml and project.json): the manifest base
        # layers beneath the ecc.toml values; a declared entry seeds the
        # creation-time flow range. Runs after run-name resolution so the
        # real workspace's parameter_patch applies.
        manifest_parameters, entry_flow_config = run_prepare.manifest_base_layer(ctx, run_name)
        if manifest_parameters:
            cfg.manifest_parameters = manifest_parameters
        if entry_flow_config is not None:
            flow_config = entry_flow_config

    protected = (project_dir, os.path.join(project_dir, "runs"))
    spelled = {os.path.normpath(p) for p in protected}
    canonical = {os.path.realpath(p) for p in protected}
    if os.path.normpath(run_dir) in spelled or os.path.realpath(run_dir) in canonical:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "invalid_run_id",
                    "run": run_name,
                    "workspace": run_dir,
                    "reason": "run id must not resolve to the project or runs container",
                }
            ]
        )
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if os.path.exists(flow_json) and not command_input.overwrite:
        return run_prepare.run_existing_workspace(
            command_input,
            ctx,
            cfg,
            run_dir,
            run_name,
            cli_overrides,
            warning_records,
            workspace_registered=workspace_registered,
        )

    if command_input.overwrite and os.path.lexists(run_dir):
        if not _resolves_as_spelled(run_dir, project_dir) or not _is_ecc_run_dir(run_dir):
            return CommandResult.err(
                [
                    {
                        "kind": "error",
                        "error": "overwrite_refused",
                        "run": run_name,
                        "workspace": run_dir,
                        "reason": "target is not an ECC run directory",
                    }
                ]
            )
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

    # Only the process that atomically creates the target may proceed or
    # clean up a failed create_workspace: an existing target (pre-existing
    # or won by a concurrent run) is never written into or removed by this
    # invocation. create_workspace re-attempts the creation, so any other
    # error surfaces from there.
    owns_target = False
    try:
        os.makedirs(run_dir)
        owns_target = True
    except FileExistsError:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "run_exists",
                    "run": run_name,
                    "workspace": run_dir,
                    "overwrite": disclosure_cmd("ecc run --overwrite", project, ctx.run_id),
                }
            ]
        )
    except OSError:
        pass

    _, origin_verilog, input_filelist = resolve_rtl(cfg)
    parameters = to_parameters(cfg)
    pdk_root = resolve_pdk_root(cfg)

    manifest_parameters = cfg.manifest_parameters
    if manifest_parameters:
        from chipcompiler.data.parameter import update_parameters
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
        backend_overrides = build_backend_overrides(resolved)
        from chipcompiler.data.parameter import update_parameters

        update_parameters(backend_overrides, parameters)

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
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "workspace_failed",
                    "run": run_name,
                    "workspace": run_dir,
                    "reason": str(exc),
                }
            ]
        )

    if workspace is None:
        if owns_target:
            shutil.rmtree(run_dir, ignore_errors=True)
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "workspace_failed",
                    "run": run_name,
                    "workspace": run_dir,
                }
            ]
        )

    if cli_overrides:
        import json

        provenance_path = os.path.join(run_dir, "home", "cli-param-overrides.json")
        os.makedirs(os.path.dirname(provenance_path), exist_ok=True)
        with open(provenance_path, "w") as _f:
            json.dump(cli_overrides, _f)

    if flow_config is None:
        # CLI-born workspaces persist the named prefix chain as their target.
        from chipcompiler.data.parameter import save_parameter

        workspace_parameters = getattr(workspace, "parameters", None)
        if workspace_parameters is not None:
            workspace_parameters.data["_flow"] = {"preset": cfg.flow_preset}
            save_parameter(workspace_parameters)

    if project_state == "virgin":
        from chipcompiler.cli.project.manifest import (
            PRESET_MANIFEST_RANGE,
            build_manifest_document,
            write_manifest_if_absent,
        )

        start_step, end_step = PRESET_MANIFEST_RANGE.get(cfg.flow_preset, ("Synth", "Harden"))
        # base_design reflects the ecc.toml-resolved config only; --set
        # values are run-scoped and never baked into the manifest.
        from chipcompiler.cli.project.manifest import resolved_base_parameters

        document = build_manifest_document(
            project_dir,
            design_name=cfg.design_name,
            base_design={
                "pdk": cfg.pdk_name,
                "pdk_root": pdk_root,
                "top_module": cfg.design_top,
                "clock": cfg.design_clock_port,
                "rtl_list": cfg.design_rtl,
                "parameters": resolved_base_parameters(cfg),
            },
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
                from chipcompiler.cli.project.manifest import write_back_workspace_status

                write_back_workspace_status(project_dir, run_name, "failed")
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
                from chipcompiler.cli.core.records import legacy_layout_hint_record

                failure_records.append(legacy_layout_hint_record(project))
            return CommandResult.err(warning_records + failure_records)
    except Exception as exc:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "flow_failed",
                    "run": run_name,
                    "workspace": run_dir,
                    "reason": str(exc),
                }
            ]
        )

    if workspace_registered:
        from chipcompiler.cli.project.manifest import write_back_workspace_status

        write_back_workspace_status(project_dir, run_name, "success")

    success_records = [
        {
            "run": run_name,
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
        }
    ]
    if ctx.project_state == "legacy":
        from chipcompiler.cli.core.records import legacy_layout_hint_record

        success_records.append(legacy_layout_hint_record(project))
    return CommandResult.ok(warning_records + success_records)


def _run_workspace(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    if ctx.project is not None or command_input.project.run_id is not None:
        return error("project_workspace_conflict")
    if command_input.overwrite:
        return error("overwrite_requires_project")
    if command_input.param_set:
        return error("set_requires_project")
    selectors = sum(
        (
            command_input.resume,
            command_input.from_step is not None,
            command_input.only is not None,
        )
    )
    if selectors > 1:
        return error("selector_conflict")
    if command_input.force and command_input.only is None:
        return error("force_requires_only")

    from chipcompiler.data import load_workspace
    from chipcompiler.engine import EngineFlow, rerun

    workspace_path = os.path.abspath(os.path.expanduser(command_input.workspace))
    try:
        workspace = load_workspace(workspace_path)
    except Exception as exc:
        return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
    if workspace is None:
        return error("invalid_workspace", workspace=workspace_path)

    # Extend/resume against the workspace's own persisted flow target before
    # building the engine flow, so appended steps are visible below.
    from chipcompiler.engine.reconcile import reconcile_workspace

    reconcile_result = reconcile_workspace(workspace_path)
    if not reconcile_result.ok:
        return error(
            "flow_mismatch",
            workspace=workspace_path,
            reason="the workspace flow target diverges from the persisted flow",
        )

    try:
        engine_flow = EngineFlow(workspace=workspace)
    except Exception as exc:
        return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
    if not engine_flow.has_init():
        return error("missing_flow", workspace=workspace_path)

    try:
        selected = rerun.selected_step_names(
            engine_flow,
            from_step=command_input.from_step,
            only=command_input.only,
            force=command_input.force,
        )
    except ValueError as exc:
        return error("unknown_step", workspace=workspace_path, reason=str(exc))

    from chipcompiler.cli.rendering.progress import preserve_cli_stdio

    try:
        with preserve_cli_stdio():
            if selected:
                engine_flow.create_step_workspaces(executable_steps=set(selected))
            if command_input.only is not None:
                result = rerun.run_only(engine_flow, command_input.only, force=command_input.force)
            elif command_input.from_step is not None:
                result = rerun.run_from(engine_flow, command_input.from_step)
            else:
                result = rerun.run_resume(engine_flow)
    except ValueError as exc:
        return error("step_unavailable", workspace=workspace_path, reason=str(exc))
    except Exception as exc:
        return error("flow_failed", workspace=workspace_path, reason=str(exc))

    record = {
        "run": "workspace",
        "status": "success" if result.ok else "failed",
        "workspace": workspace_path,
        "executed_steps": list(result.executed),
        "no_op": result.ok and not result.executed,
    }
    if result.ok:
        return CommandResult.ok([record])
    record["failed_step"] = result.failed
    record["resume_cmd"] = f"ecc run --workspace {shlex.quote(workspace_path)} --resume"
    return CommandResult.err([record])
