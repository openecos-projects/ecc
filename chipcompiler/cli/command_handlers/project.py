import os
import shutil
import sys

from chipcompiler.cli.core.inputs import CheckInput, InitInput, RunInput
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
    os.makedirs(os.path.join(project_dir, "runs"), exist_ok=True)

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
    from chipcompiler.cli.project.config import (
        find_config_path,
        load_project_config,
        validate_project_config,
    )

    project = ctx.project

    config_path = find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )

    cfg = load_project_config(config_path)
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

    records = [
        {
            "project": cfg.design_name,
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": "runs/default",
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

    return CommandResult.ok(records)


def run(command_input: RunInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.config import (
        find_config_path,
        load_project_config,
        resolve_pdk_root,
        resolve_rtl,
        to_parameters,
        validate_project_config,
    )
    from chipcompiler.data import create_workspace
    from chipcompiler.engine import EngineFlow
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    project = ctx.project
    project_dir = ctx.project_dir

    config_path = find_config_path(project_dir)
    if config_path is None:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "missing_config",
                    "path": os.path.join(project_dir, "ecc.toml"),
                }
            ]
        )

    cfg = load_project_config(config_path)
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

    run_dir = os.path.join(project_dir, "runs", "default")
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if os.path.exists(flow_json) and not command_input.overwrite:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "run_exists",
                    "run": "default",
                    "workspace": run_dir,
                    "overwrite": disclosure_cmd("ecc run --overwrite", project),
                }
            ]
        )

    if command_input.overwrite and os.path.exists(run_dir):
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

    _, origin_verilog, input_filelist = resolve_rtl(cfg)
    parameters = to_parameters(cfg)
    pdk_root = resolve_pdk_root(cfg)

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
            origin_def="",
            origin_verilog=origin_verilog,
            pdk=cfg.pdk_name,
            parameters=parameters,
            input_filelist=input_filelist,
            pdk_root=pdk_root,
        )
    except Exception as exc:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "workspace_failed",
                    "run": "default",
                    "workspace": run_dir,
                    "reason": str(exc),
                }
            ]
        )

    if workspace is None:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "workspace_failed",
                    "run": "default",
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

    try:
        engine_flow = EngineFlow(workspace=workspace)
        if not engine_flow.has_init():
            for step, tool, state in build_rtl2gds_flow():
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
            return CommandResult.err(
                [
                    {
                        "run": "default",
                        "status": "failed",
                        "workspace": run_dir,
                        "inspect_cmd": disclosure_cmd("ecc status", project),
                        "log": disclosure_cmd("ecc log", project),
                    }
                ]
            )
    except Exception as exc:
        return CommandResult.err(
            [
                {
                    "kind": "error",
                    "error": "flow_failed",
                    "run": "default",
                    "workspace": run_dir,
                    "reason": str(exc),
                }
            ]
        )

    return CommandResult.ok(
        [
            {
                "run": "default",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": disclosure_cmd("ecc status", project),
                "metrics_cmd": disclosure_cmd("ecc metrics", project),
                "log_cmd": disclosure_cmd("ecc log", project),
            }
        ]
    )
