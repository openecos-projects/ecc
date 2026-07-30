import os

from chipcompiler.cli.core.inputs import (
    ConfigInput,
    LogInput,
    StatusInput,
)
from chipcompiler.cli.core.output import (
    disclosure_cmd,
    normalize_state,
    normalize_step_name,
)
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.config import InvalidFlowRun, config_run_id_from


def _config_error_result(ctx: CommandContext, reason: str) -> CommandResult:
    return CommandResult.err(
        [
            error_record(
                "config_error",
                reason=reason,
                inspect=disclosure_cmd("ecc check", ctx.project),
            )
        ]
    )


def status(command_input: StatusInput, ctx: CommandContext) -> CommandResult:
    if ctx.config_error:
        return _config_error_result(ctx, ctx.config_error)

    from chipcompiler.cli.inspection.discovery import (
        CORRUPT_FLOW_JSON,
        _safe_steps,
        get_run_status,
        read_flow_json,
    )

    flow_data = read_flow_json(ctx.run_dir)
    display_run = ctx.run_id or "default"
    project = ctx.project

    if flow_data is None:
        return CommandResult.err(
            [
                {
                    "run": display_run,
                    "status": "missing",
                    "workspace": ctx.run_dir,
                    "start_cmd": disclosure_cmd("ecc run", project, ctx.run_id),
                }
            ]
        )

    if flow_data is CORRUPT_FLOW_JSON:
        return CommandResult.err(
            [
                {
                    "run": display_run,
                    "status": "corrupt",
                    "workspace": ctx.run_dir,
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                    "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
                }
            ]
        )

    run_status = get_run_status(flow_data)
    records = [
        {
            "run": display_run,
            "status": run_status,
            "workspace": ctx.run_dir,
            "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
            "log_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
        }
    ]

    for step in _safe_steps(flow_data):
        step_token = normalize_step_name(step.get("name", ""))
        records.append(
            {
                "step": step_token,
                "tool": step.get("tool", ""),
                "status": normalize_state(step.get("state", "")),
                "runtime": step.get("runtime", "") or None,
                "log_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
            }
        )

    return CommandResult.ok(records)


def log(command_input: LogInput, ctx: CommandContext) -> CommandResult:
    if ctx.config_error:
        return _config_error_result(ctx, ctx.config_error)

    from chipcompiler.cli.inspection.discovery import (
        discover_logs,
        discover_step_dirs,
        get_flow_step_names,
        listing_step_order,
    )
    from chipcompiler.cli.inspection.log_view import build_log_records

    step_token = command_input.step
    project = ctx.project

    if step_token is None:
        records = []

        for lf in discover_logs(ctx.run_dir):
            records.append(
                {
                    "log": os.path.relpath(lf, ctx.run_dir),
                    "inspect_cmd": disclosure_cmd("ecc log", project, ctx.run_id),
                }
            )

        for token in listing_step_order(ctx.run_dir):
            for lf in discover_logs(ctx.run_dir, token):
                records.append(
                    {
                        "step": token,
                        "source": os.path.relpath(lf, ctx.run_dir),
                        "inspect_cmd": disclosure_cmd(f"ecc log {token}", project, ctx.run_id),
                    }
                )

        if not records:
            return CommandResult.ok(
                [
                    {
                        "log_status": "no_logs",
                        "workspace": ctx.run_dir,
                        "run": disclosure_cmd("ecc run", project, ctx.run_id),
                    }
                ]
            )
        return CommandResult.ok(records)

    step_dirs = discover_step_dirs(ctx.run_dir)
    if step_token not in step_dirs:
        flow_steps = get_flow_step_names(ctx.run_dir)
        if step_token in flow_steps:
            return CommandResult.err(
                [
                    {
                        "step": step_token,
                        "log_status": "missing",
                        "inspect_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                    }
                ]
            )
        return CommandResult.err(
            [
                {
                    "step": step_token,
                    "status": "unknown_step",
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                }
            ]
        )

    log_files = discover_logs(ctx.run_dir, step_token)
    if not log_files:
        return CommandResult.err(
            [
                {
                    "step": step_token,
                    "log_status": "missing",
                    "source": os.path.relpath(
                        os.path.join(step_dirs[step_token], "log"),
                        ctx.run_dir,
                    ),
                    "inspect_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                }
            ]
        )

    inspect_cmd = disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id)

    all_records = []
    for lf in log_files:
        source = os.path.relpath(lf, ctx.run_dir)
        try:
            with open(lf, errors="replace") as f:
                raw = f.read().splitlines()
        except OSError as exc:
            return CommandResult.err(
                [
                    {
                        "step": step_token,
                        "log_status": "unreadable",
                        "source": source,
                        "error": str(exc),
                        "inspect_cmd": inspect_cmd,
                    }
                ]
            )
        if not raw:
            continue
        all_records.extend(build_log_records(step_token, source, raw, inspect_cmd))

    if not all_records:
        return CommandResult.ok(
            [
                {
                    "step": step_token,
                    "log_status": "empty",
                    "inspect_cmd": inspect_cmd,
                }
            ]
        )

    return CommandResult.ok(all_records)


def config(command_input: ConfigInput, ctx: CommandContext) -> CommandResult:
    configured = config_run_id_from(ctx.config)
    if isinstance(configured, InvalidFlowRun):
        return _config_error_result(ctx, configured.problem)

    from chipcompiler.cli.inspection.config_view import (
        build_project_config_items,
        build_step_config_items,
    )

    step_token = command_input.step
    project = ctx.project

    if step_token is not None:
        items, rc = build_step_config_items(
            ctx.run_dir,
            step_token,
            project,
            ctx.run_id,
            ctx.project_dir,
        )
    else:
        items, rc = build_project_config_items(
            ctx.project_dir,
            ctx.run_dir,
            project,
            ctx.run_id,
        )

    if rc != 0:
        first = items[0] if items else {}
        status_value = first.get("status")
        if status_value == "unknown_step":
            return CommandResult.err(
                [
                    {
                        "step": first.get("step", ""),
                        "status": "unknown_step",
                        "inspect": disclosure_cmd("ecc status", project, ctx.run_id),
                    }
                ]
            )
        if status_value == "missing_config":
            return CommandResult.err(
                [
                    error_record(
                        "missing_config",
                        inspect=disclosure_cmd("ecc check", project),
                    )
                ]
            )
        if status_value == "invalid_config":
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
        return CommandResult.ok(
            [
                {
                    "step": first["step"],
                    "config_status": "none",
                }
            ]
        )

    records = []
    for item in items:
        if item.get("kind") == "param":
            records.append(
                {
                    "kind": "param",
                    "config": item["key"],
                    "key": item["key"],
                    "scope": "project",
                    "value": item["value"],
                    "default": item.get("default"),
                    "source": item["source"],
                    "maps_to": item.get("maps_to"),
                    "inspect": item.get("inspect_cmd"),
                }
            )
        elif item.get("scope") == "project":
            records.append(
                {
                    "config": item["key"],
                    "scope": "project",
                    "value": item["value"],
                    "resolved": item.get("resolved"),
                    "source": item["source"],
                    "inspect": item.get("inspect_cmd"),
                }
            )
        else:
            records.append(
                {
                    "config": os.path.basename(item["path"]),
                    "scope": "step",
                    "step": item["step"],
                    "role": item["role"],
                    "run": item.get("run", "default"),
                    "path": item["path"],
                    "source": item["source"],
                    "inspect": item.get("inspect_cmd"),
                }
            )
    return CommandResult.ok(records)
