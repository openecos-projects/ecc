import contextlib
import os
import shlex

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


def check(command_input: CheckInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project import effective_config

    project = ctx.project

    if ctx.manifest_error:
        # Hybrid projects also resolve the run selector through the
        # manifest; an unresolvable selection is an error, not a warning.
        from chipcompiler.cli.core.records import manifest_error_record

        return CommandResult.err(
            [
                manifest_error_record(
                    ctx.manifest_error,
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    # Both manifest-only and hybrid projects validate the effective config:
    # manifest fallback applied, entry layer resolved, manifest relaxations
    # honored, every declared RTL source checked.
    cfg = ctx.config
    entry_warnings: list[dict] = []
    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, _entry_flow_config, entry_warnings = resolved_cfg
    elif cfg is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    errors = effective_config.validate_effective(ctx, cfg, fresh=False, flow_config=None)

    if errors:
        return CommandResult.err(
            [
                {
                    "check": "config",
                    "status": "fail",
                    "reason": err,
                    "source": "ecc.toml" if ctx.config is not None else "project.json",
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
            "config": "ecc.toml" if ctx.config is not None else "project.json",
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

    records.extend(entry_warnings)

    return CommandResult.ok(records)


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

    from chipcompiler.cli.project import run_dispatch, run_prepare

    project_dir = ctx.project_dir

    cfg = ctx.config
    flow_config = None
    layer_warnings: list[dict] = []
    if cfg is None and ctx.project_state != "manifest":
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "missing_config",
                    "path": os.path.join(project_dir, "ecc.toml"),
                }
            ]
        )

    from chipcompiler.cli.project import effective_config

    if ctx.project_state == "manifest":
        resolved_cfg = effective_config.resolve_effective_config(
            ctx, command_input.project.run_id, cfg
        )
        if isinstance(resolved_cfg, CommandResult):
            return resolved_cfg
        cfg, flow_config, entry_warnings = resolved_cfg
        layer_warnings.extend(entry_warnings)

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
    warning_records = layer_warnings + warning_records

    flow_json = os.path.join(run_dir, "home", "flow.json")
    errors = effective_config.validate_effective(
        ctx,
        cfg,
        # An overwrite wipes and recreates the target, so it validates as a
        # fresh run (a derivable flow target is required) even when the
        # ledger still exists at preflight time.
        fresh=not os.path.exists(flow_json) or command_input.overwrite,
        flow_config=flow_config,
        cli_overrides=cli_overrides,
    )
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

    return run_dispatch.dispatch_project_run(
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
    )


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
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
    )
    from chipcompiler.engine.reconcile import classify_workspace, reconcile_workspace

    # Pure-read preflight: a divergent flow is rejected BEFORE load_workspace
    # can migrate configs, create home.json/checklist, or take the lock.
    probe = classify_workspace(workspace_path)
    if probe.outcome == "mismatch":
        reason = probe.error or ""
        if reason.startswith("workspace_config_invalid"):
            return error("workspace_config_invalid", workspace=workspace_path, reason=reason)
        return error(
            "flow_mismatch",
            workspace=workspace_path,
            reason="the workspace flow target diverges from the persisted flow",
        )

    try:
        workspace = load_workspace(workspace_path)
    except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
        return error("workspace_config_invalid", workspace=workspace_path, reason=str(exc))
    except Exception as exc:
        return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
    if workspace is None:
        return error("invalid_workspace", workspace=workspace_path)

    # Extend/resume against the workspace's own persisted flow target before
    # building the engine flow, so appended steps are visible below.
    reconcile_result = reconcile_workspace(workspace_path)
    if not reconcile_result.ok:
        reason = reconcile_result.error or ""
        if reason.startswith("flow_adopt_failed"):
            return error("flow_adopt_failed", workspace=workspace_path, reason=reason)
        return error(
            "flow_mismatch",
            workspace=workspace_path,
            reason="the workspace flow target diverges from the persisted flow",
        )
    if (
        reconcile_result.outcome == "no_op"
        and reconcile_result.persisted
        and command_input.from_step is None
        and command_input.only is None
    ):
        # The persisted flow already covers the target and succeeded;
        # resume has nothing to do. Explicit selectors (--from/--only)
        # still re-execute on request.
        return CommandResult.ok(
            [
                {
                    "run": "workspace",
                    "status": "success",
                    "workspace": workspace_path,
                    "executed_steps": [],
                    "no_op": True,
                }
            ]
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
