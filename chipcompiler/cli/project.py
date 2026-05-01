import os
import shutil
import sys

from chipcompiler.cli.config import (
    find_config_path,
    load_project_config,
    resolve_pdk_root,
    resolve_rtl,
    to_parameters,
    validate_project_config,
)
from chipcompiler.cli.output import disclosure_cmd, format_line
from chipcompiler.data import create_workspace
from chipcompiler.engine import EngineFlow
from chipcompiler.rtl2gds import build_rtl2gds_flow

DEFAULT_TOML = '''[design]
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
'''


def init_project(name: str, project: str | None = None) -> tuple[list[str], int]:
    if not name or not name.strip():
        print(format_line(error="project name is required"), file=sys.stderr)
        return [], 1

    project_dir = os.path.abspath(name)
    config_path = os.path.join(project_dir, "ecc.toml")
    design_name = os.path.basename(project_dir)

    if os.path.exists(config_path):
        print(format_line(
            error="already_exists",
            path=config_path,
        ), file=sys.stderr)
        return [], 1

    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "rtl"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "constraints"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "runs"), exist_ok=True)

    with open(config_path, "w") as f:
        f.write(DEFAULT_TOML.format(name=design_name))

    project_arg = project or name
    line = format_line(
        project=name,
        status="created",
        path=name,
        check=disclosure_cmd("ecc check", project_arg),
        run=disclosure_cmd("ecc run", project_arg),
    )
    return [line], 0


def check_project(project_dir: str, project: str | None = None) -> tuple[list[str], int]:
    config_path = find_config_path(project_dir)
    if config_path is None:
        print(format_line(
            error="missing_config",
            path=os.path.join(project_dir, "ecc.toml"),
        ), file=sys.stderr)
        return [], 1

    cfg = load_project_config(config_path)
    errors = validate_project_config(cfg)

    lines = []

    if errors:
        for err in errors:
            lines.append(format_line(
                check="config",
                status="fail",
                reason=err,
                source="ecc.toml",
                inspect=disclosure_cmd("ecc check --json", project),
            ))
        return lines, 1

    lines.append(format_line(
        project=cfg.design_name,
        status="checked",
        config="ecc.toml",
        run_dir="runs/default",
        run=disclosure_cmd("ecc run", project),
        status_cmd=disclosure_cmd("ecc status", project),
    ))

    if cfg.design_rtl:
        lines.append(format_line(
            check="rtl",
            status="pass",
            path=cfg.design_rtl[0],
            inspect=disclosure_cmd("ecc check --json", project),
        ))

    return lines, 0


def run_project(project_dir: str, overwrite: bool = False,
                project: str | None = None) -> tuple[list[str], int]:
    config_path = find_config_path(project_dir)
    if config_path is None:
        print(format_line(
            error="missing_config",
            path=os.path.join(project_dir, "ecc.toml"),
        ), file=sys.stderr)
        return [], 1

    cfg = load_project_config(config_path)
    errors = validate_project_config(cfg)
    if errors:
        for err in errors:
            print(format_line(error="config_error", reason=err), file=sys.stderr)
        return [], 1

    run_dir = os.path.join(project_dir, "runs", "default")
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if os.path.exists(flow_json) and not overwrite:
        print(format_line(
            error="run_exists",
            run="default",
            workspace=run_dir,
            overwrite=disclosure_cmd("ecc run --overwrite", project),
        ), file=sys.stderr)
        return [], 1

    if overwrite and os.path.exists(run_dir):
        shutil.rmtree(run_dir)

    _, origin_verilog, input_filelist = resolve_rtl(cfg)
    parameters = to_parameters(cfg)
    pdk_root = resolve_pdk_root(cfg)

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
        print(format_line(
            error="workspace_failed",
            run="default",
            workspace=run_dir,
            reason=str(exc),
        ), file=sys.stderr)
        return [], 1

    if workspace is None:
        print(format_line(
            error="workspace_failed",
            run="default",
            workspace=run_dir,
        ), file=sys.stderr)
        return [], 1

    try:
        engine_flow = EngineFlow(workspace=workspace)
        if not engine_flow.has_init():
            for step, tool, state in build_rtl2gds_flow():
                engine_flow.add_step(step=step, tool=tool, state=state)

        engine_flow.create_step_workspaces()

        if not engine_flow.run_steps():
            print(format_line(
                run="default",
                status="failed",
                workspace=run_dir,
                status_cmd=disclosure_cmd("ecc status", project),
                log=disclosure_cmd("ecc log", project),
            ), file=sys.stderr)
            return [], 1
    except Exception as exc:
        print(format_line(
            error="flow_failed",
            run="default",
            workspace=run_dir,
            reason=str(exc),
        ), file=sys.stderr)
        return [], 1

    lines = [format_line(
        run="default",
        status="success",
        workspace=run_dir,
        status_cmd=disclosure_cmd("ecc status", project),
        metrics=disclosure_cmd("ecc metrics", project),
        log=disclosure_cmd("ecc log", project),
    )]
    return lines, 0
