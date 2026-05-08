import os
import shutil
import sys

from chipcompiler.cli.types import CommandContext, CommandResult
from chipcompiler.cli.records import error_record
from chipcompiler.cli.output import (
    disclosure_cmd,
    normalize_metric_key,
    normalize_state,
    normalize_step_name,
)


def param(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.param_handler import (
        param_diff,
        param_list,
        param_set,
        param_show,
        param_unset,
    )

    subcmd = getattr(args, "param_command", None)
    handlers = {
        "list": param_list,
        "show": param_show,
        "set": param_set,
        "unset": param_unset,
        "diff": param_diff,
    }
    handler = handlers.get(subcmd)
    if handler is None:
        return CommandResult.err([error_record("missing_subcommand")], exit_code=1)
    return handler(args, ctx)


def status(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspect import (
        CORRUPT_FLOW_JSON,
        _safe_steps,
        get_run_status,
        read_flow_json,
    )

    flow_data = read_flow_json(ctx.run_dir)
    display_run = ctx.run_id or "default"
    project = ctx.project

    if flow_data is None:
        return CommandResult.err([{
            "run": display_run,
            "status": "missing",
            "workspace": ctx.run_dir,
            "start_cmd": disclosure_cmd("ecc run", project),
        }])

    if flow_data is CORRUPT_FLOW_JSON:
        return CommandResult.err([{
            "run": display_run,
            "status": "corrupt",
            "workspace": ctx.run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
        }])

    run_status = get_run_status(flow_data)
    records = [{
        "run": display_run,
        "status": run_status,
        "workspace": ctx.run_dir,
        "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        "metrics_cmd": disclosure_cmd("ecc metrics", project, ctx.run_id),
        "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
    }]

    for step in _safe_steps(flow_data):
        step_token = normalize_step_name(step.get("name", ""))
        records.append({
            "step": step_token,
            "tool": step.get("tool", ""),
            "status": normalize_state(step.get("state", "")),
            "runtime": step.get("runtime", "") or None,
            "metrics_cmd": disclosure_cmd(f"ecc metrics {step_token}", project, ctx.run_id),
            "log_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
        })

    return CommandResult.ok(records)


def log(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspect import (
        discover_logs,
        discover_step_dirs,
        get_flow_step_names,
        listing_step_order,
    )
    from chipcompiler.cli.log_view import build_log_records

    step_token = args.step
    project = ctx.project

    if step_token is None:
        records = []

        for lf in discover_logs(ctx.run_dir):
            records.append({
                "log": os.path.relpath(lf, ctx.run_dir),
                "inspect_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
            })

        for token in listing_step_order(ctx.run_dir):
            for lf in discover_logs(ctx.run_dir, token):
                records.append({
                    "step": token,
                    "source": os.path.relpath(lf, ctx.run_dir),
                    "inspect_cmd": disclosure_cmd(f"ecc log {token}", project, ctx.run_id),
                })

        if not records:
            return CommandResult.ok([{
                "log_status": "no_logs",
                "workspace": ctx.run_dir,
                "run": disclosure_cmd("ecc run", project),
            }])
        return CommandResult.ok(records)

    step_dirs = discover_step_dirs(ctx.run_dir)
    if step_token not in step_dirs:
        flow_steps = get_flow_step_names(ctx.run_dir)
        if step_token in flow_steps:
            return CommandResult.err([{
                "step": step_token,
                "log_status": "missing",
                "inspect_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
            }])
        return CommandResult.err([{
            "step": step_token,
            "status": "unknown_step",
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        }])

    log_files = discover_logs(ctx.run_dir, step_token)
    if not log_files:
        return CommandResult.err([{
            "step": step_token,
            "log_status": "missing",
            "source": os.path.relpath(
                os.path.join(step_dirs[step_token], "log"), ctx.run_dir,
            ),
            "inspect_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
        }])

    inspect_cmd = disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id)

    all_records = []
    for lf in log_files:
        source = os.path.relpath(lf, ctx.run_dir)
        try:
            with open(lf, errors="replace") as f:
                raw = f.read().splitlines()
        except OSError as exc:
            return CommandResult.err([{
                "step": step_token,
                "log_status": "unreadable",
                "source": source,
                "error": str(exc),
                "inspect_cmd": inspect_cmd,
            }])
        if not raw:
            continue
        all_records.extend(build_log_records(step_token, source, raw, inspect_cmd))

    if not all_records:
        return CommandResult.ok([{
            "step": step_token,
            "log_status": "empty",
            "inspect_cmd": inspect_cmd,
        }])

    return CommandResult.ok(all_records)


def metrics(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspect import (
        _internal_from_token,
        discover_metrics,
        discover_step_dirs,
        get_flow_step_names,
        read_metrics,
    )

    step_token = args.step
    project = ctx.project

    metrics_files = discover_metrics(ctx.run_dir, step_token)
    if not metrics_files:
        if step_token is not None:
            step_dirs = discover_step_dirs(ctx.run_dir)
            flow_steps = get_flow_step_names(ctx.run_dir)
            if step_token in step_dirs:
                return CommandResult.err([{
                    "metric_step": step_token,
                    "status": "missing",
                    "path": os.path.relpath(
                        os.path.join(step_dirs[step_token], "analysis",
                                     f"{_internal_from_token(step_token)}_metrics.json"),
                        ctx.run_dir,
                    ),
                    "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                }])
            if step_token in flow_steps:
                return CommandResult.err([{
                    "metric_step": step_token,
                    "status": "missing",
                    "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                }])
            return CommandResult.err([{
                "step": step_token,
                "status": "unknown_step",
                "inspect": disclosure_cmd("ecc status", project, ctx.run_id),
            }])
        return CommandResult.ok([{
            "metrics_status": "none",
            "workspace": ctx.run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        }])

    records = []
    has_corrupt = False
    for token, path in sorted(metrics_files.items()):
        data = read_metrics(path)
        if data is None:
            has_corrupt = True
            records.append({
                "metric_step": token,
                "status": "corrupt",
                "path": os.path.relpath(path, ctx.run_dir),
                "log_cmd": disclosure_cmd(f"ecc log {token}", project, ctx.run_id),
            })
            continue
        for raw_key, value in data.items():
            norm_key = normalize_metric_key(raw_key)
            records.append({
                "metric": norm_key,
                "step": token,
                "value": value,
                "source": os.path.relpath(path, ctx.run_dir),
                "inspect": disclosure_cmd(f"ecc metrics {token} --json", project, ctx.run_id),
            })

    if has_corrupt:
        return CommandResult.err(records)
    return CommandResult.ok(records)


def artifacts(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.artifacts import discover_artifacts

    step_token = args.step
    project = ctx.project

    artifact_records, rc = discover_artifacts(
        ctx.run_dir, step_token, project, ctx.run_id, ctx.project_dir,
    )

    if rc != 0:
        if artifact_records and artifact_records[0].get("status") == "unknown_step":
            return CommandResult.err([{
                "step": artifact_records[0]["step"],
                "status": "unknown_step",
                "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            }])
        return CommandResult.err(artifact_records)

    if not artifact_records:
        if step_token is not None:
            return CommandResult.ok([{
                "step": step_token,
                "artifacts_status": "none",
                "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
            }])
        return CommandResult.ok([{
            "artifacts_status": "none",
            "workspace": ctx.run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
        }])

    records = []
    for a in artifact_records:
        line_fields = {
            "artifact": os.path.basename(a["path"]),
            "step": a["step"],
            "role": a["role"],
            "path": a["path"],
            "inspect": disclosure_cmd(f"ecc artifacts {a['step']} --json", project, ctx.run_id),
        }
        if a["role"] == "analysis":
            line_fields["metrics"] = disclosure_cmd(f"ecc metrics {a['step']}", project, ctx.run_id)
        if a["role"] == "log":
            line_fields["inspect"] = disclosure_cmd(f"ecc log {a['step']}", project, ctx.run_id)
        if a["role"] in ("output", "report", "analysis", "log"):
            line_fields["config"] = disclosure_cmd(f"ecc config {a['step']} --resolved", project, ctx.run_id)
        records.append(line_fields)
    return CommandResult.ok(records)


def config(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.config_view import build_project_config_items, build_step_config_items

    step_token = args.step
    project = ctx.project

    if step_token is not None:
        items, rc = build_step_config_items(
            ctx.run_dir, step_token, project, ctx.run_id, ctx.project_dir,
        )
    else:
        items, rc = build_project_config_items(
            ctx.project_dir, ctx.run_dir, project, ctx.run_id,
        )

    if rc != 0:
        first = items[0] if items else {}
        status = first.get("status")
        if status == "unknown_step":
            return CommandResult.err([{
                "step": first.get("step", ""),
                "status": "unknown_step",
                "inspect": disclosure_cmd("ecc status", project, ctx.run_id),
            }])
        if status == "missing_config":
            return CommandResult.err([error_record(
                "missing_config",
                inspect=disclosure_cmd("ecc check", project),
            )])
        if status == "invalid_config":
            reason = first.get("reason")
            rec = error_record(
                "invalid_config",
                inspect=disclosure_cmd("ecc check", project),
            )
            if reason:
                rec["reason"] = reason
            return CommandResult.err([rec])
        return CommandResult.err(items)

    if not items:
        return CommandResult.ok([{"config_status": "none"}])

    first = items[0]
    if first.get("config_status") == "none":
        return CommandResult.ok([{
            "step": first["step"],
            "config_status": "none",
            "artifacts": first.get("artifacts"),
        }])

    records = []
    for item in items:
        if item.get("kind") == "param":
            records.append({
                "kind": "param",
                "config": item["key"],
                "key": item["key"],
                "scope": "project",
                "value": item["value"],
                "default": item.get("default"),
                "source": item["source"],
                "maps_to": item.get("maps_to"),
                "inspect": item.get("inspect_cmd"),
            })
        elif item.get("scope") == "project":
            records.append({
                "config": item["key"],
                "scope": "project",
                "value": item["value"],
                "resolved": item.get("resolved"),
                "source": item["source"],
                "inspect": item.get("inspect_cmd"),
            })
        else:
            records.append({
                "config": os.path.basename(item["path"]),
                "scope": "step",
                "step": item["step"],
                "role": item["role"],
                "run": item.get("run", "default"),
                "path": item["path"],
                "source": item["source"],
                "inspect": item.get("inspect_cmd"),
            })
    return CommandResult.ok(records)


def diagnose(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.diagnose import build_diagnose_issues

    step_token = args.step
    project = ctx.project
    display_run = ctx.run_id or "default"

    issues, _ = build_diagnose_issues(ctx.run_dir, step_token, project, ctx.run_id)

    if not issues:
        return CommandResult.ok([{
            "status": "clean",
            "run": display_run,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "artifacts": disclosure_cmd("ecc artifacts", project, ctx.run_id),
            "config": disclosure_cmd("ecc config --resolved", project, ctx.run_id),
        }])

    has_error = any(i.get("severity") == "error" for i in issues)
    text_keys = (
        "issue", "severity", "run", "step", "status", "count",
        "evidence", "log", "artifacts", "config", "start_cmd",
    )
    records = []
    for issue in issues:
        records.append({k: issue[k] for k in text_keys if k in issue})

    if has_error:
        return CommandResult.err(records)
    return CommandResult.ok(records)


def init(args, ctx: CommandContext) -> CommandResult:
    name = args.name
    if not name or not name.strip():
        return CommandResult.err([{"kind": "error", "error": "project name is required"}])

    project_dir = os.path.abspath(name)
    config_path = os.path.join(project_dir, "ecc.toml")
    design_name = os.path.basename(project_dir)

    if os.path.isfile(project_dir):
        return CommandResult.err([{
            "kind": "error",
            "error": "path_is_file",
            "path": project_dir,
        }])

    if os.path.exists(config_path):
        return CommandResult.err([{
            "kind": "error",
            "error": "already_exists",
            "path": config_path,
        }])

    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "rtl"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "constraints"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "runs"), exist_ok=True)

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

    with open(config_path, "w") as f:
        f.write(DEFAULT_TOML.format(name=design_name))

    project_arg = ctx.project or name
    return CommandResult.ok([{
        "project": name,
        "status": "created",
        "path": name,
        "check": disclosure_cmd("ecc check", project_arg),
        "run": disclosure_cmd("ecc run", project_arg),
    }])


def check(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.config import (
        find_config_path,
        load_project_config,
        validate_project_config,
    )

    project = ctx.project

    config_path = find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record(
            "missing_config",
            path=os.path.join(ctx.project_dir, "ecc.toml"),
            inspect=disclosure_cmd("ecc check", project),
        )])

    cfg = load_project_config(config_path)
    errors = validate_project_config(cfg)

    if errors:
        return CommandResult.err([{
            "check": "config",
            "status": "fail",
            "reason": err,
            "source": "ecc.toml",
            "inspect": disclosure_cmd("ecc check --json", project),
        } for err in errors])

    records = [{
        "project": cfg.design_name,
        "status": "checked",
        "config": "ecc.toml",
        "run_dir": "runs/default",
        "run": disclosure_cmd("ecc run", project),
        "inspect_cmd": disclosure_cmd("ecc status", project),
    }]

    if cfg.design_rtl:
        records.append({
            "check": "rtl",
            "status": "pass",
            "path": cfg.design_rtl[0],
            "inspect": disclosure_cmd("ecc check --json", project),
        })

    return CommandResult.ok(records)


def run(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.config import (
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
        return CommandResult.err([{
            "kind": "error",
            "error": "missing_config",
            "path": os.path.join(project_dir, "ecc.toml"),
        }])

    cfg = load_project_config(config_path)
    errors = validate_project_config(cfg)
    if errors:
        return CommandResult.err([{
            "kind": "error",
            "error": "config_error",
            "reason": err,
        } for err in errors])

    # Parse and validate --set overrides before workspace creation
    cli_overrides = {}
    raw_sets = getattr(args, "param_set", [])
    if raw_sets:
        from chipcompiler.cli.params import parse_cli_overrides
        cli_overrides, set_errors = parse_cli_overrides(raw_sets)
        if set_errors:
            return CommandResult.err([{
                "kind": "error",
                "error": "invalid_parameter",
                "reason": err,
            } for err in set_errors])

    run_dir = os.path.join(project_dir, "runs", "default")
    flow_json = os.path.join(run_dir, "home", "flow.json")

    if os.path.exists(flow_json) and not args.overwrite:
        return CommandResult.err([{
            "kind": "error",
            "error": "run_exists",
            "run": "default",
            "workspace": run_dir,
            "overwrite": disclosure_cmd("ecc run --overwrite", project),
        }])

    if args.overwrite and os.path.exists(run_dir):
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

    # Merge resolved parameter overrides into workspace parameters
    if cfg.params_overrides or cli_overrides:
        from chipcompiler.cli.params import (
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
        return CommandResult.err([{
            "kind": "error",
            "error": "workspace_failed",
            "run": "default",
            "workspace": run_dir,
            "reason": str(exc),
        }])

    if workspace is None:
        return CommandResult.err([{
            "kind": "error",
            "error": "workspace_failed",
            "run": "default",
            "workspace": run_dir,
        }])

    # Persist CLI parameter provenance for config --resolved inspection
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

        from chipcompiler.cli.progress import (
            run_flow_with_progress,
            should_enable_run_progress,
        )

        if should_enable_run_progress(ctx, sys.stderr):
            flow_ok = run_flow_with_progress(engine_flow, ctx, project, sys.stderr)
        else:
            flow_ok = engine_flow.run_steps()

        if not flow_ok:
            return CommandResult.err([{
                "run": "default",
                "status": "failed",
                "workspace": run_dir,
                "inspect_cmd": disclosure_cmd("ecc status", project),
                "log": disclosure_cmd("ecc log", project),
            }])
    except Exception as exc:
        return CommandResult.err([{
            "kind": "error",
            "error": "flow_failed",
            "run": "default",
            "workspace": run_dir,
            "reason": str(exc),
        }])

    return CommandResult.ok([{
        "run": "default",
        "status": "success",
        "workspace": run_dir,
        "inspect_cmd": disclosure_cmd("ecc status", project),
        "metrics_cmd": disclosure_cmd("ecc metrics", project),
        "log_cmd": disclosure_cmd("ecc log", project),
    }])
