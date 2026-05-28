import os

from chipcompiler.cli.core.inputs import (
    ConfigInput,
    DiagnoseInput,
    LogInput,
    StatusInput,
    StepInspectInput,
)
from chipcompiler.cli.core.output import (
    disclosure_cmd,
    normalize_metric_key,
    normalize_state,
    normalize_step_name,
)
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def status(command_input: StatusInput, ctx: CommandContext) -> CommandResult:
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
                    "start_cmd": disclosure_cmd("ecc run", project),
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
            "metrics_cmd": disclosure_cmd("ecc metrics", project, ctx.run_id),
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
                "metrics_cmd": disclosure_cmd(f"ecc metrics {step_token}", project, ctx.run_id),
                "log_cmd": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
            }
        )

    return CommandResult.ok(records)


def log(command_input: LogInput, ctx: CommandContext) -> CommandResult:
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
                        "run": disclosure_cmd("ecc run", project),
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


def metrics(command_input: StepInspectInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspection.discovery import (
        _internal_from_token,
        discover_metrics,
        discover_step_dirs,
        get_flow_step_names,
        read_metrics,
    )

    step_token = command_input.step
    project = ctx.project

    metrics_files = discover_metrics(ctx.run_dir, step_token)
    if not metrics_files:
        if step_token is not None:
            step_dirs = discover_step_dirs(ctx.run_dir)
            flow_steps = get_flow_step_names(ctx.run_dir)
            if step_token in step_dirs:
                return CommandResult.err(
                    [
                        {
                            "metric_step": step_token,
                            "status": "missing",
                            "path": os.path.relpath(
                                os.path.join(
                                    step_dirs[step_token],
                                    "analysis",
                                    f"{_internal_from_token(step_token)}_metrics.json",
                                ),
                                ctx.run_dir,
                            ),
                            "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                        }
                    ]
                )
            if step_token in flow_steps:
                return CommandResult.err(
                    [
                        {
                            "metric_step": step_token,
                            "status": "missing",
                            "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                        }
                    ]
                )
            return CommandResult.err(
                [
                    {
                        "step": step_token,
                        "status": "unknown_step",
                        "inspect": disclosure_cmd("ecc status", project, ctx.run_id),
                    }
                ]
            )
        return CommandResult.ok(
            [
                {
                    "metrics_status": "none",
                    "workspace": ctx.run_dir,
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                }
            ]
        )

    records = []
    has_corrupt = False
    for token, path in sorted(metrics_files.items()):
        data = read_metrics(path)
        if data is None:
            has_corrupt = True
            records.append(
                {
                    "metric_step": token,
                    "status": "corrupt",
                    "path": os.path.relpath(path, ctx.run_dir),
                    "log_cmd": disclosure_cmd(f"ecc log {token}", project, ctx.run_id),
                }
            )
            continue
        for raw_key, value in data.items():
            norm_key = normalize_metric_key(raw_key)
            records.append(
                {
                    "metric": norm_key,
                    "step": token,
                    "value": value,
                    "source": os.path.relpath(path, ctx.run_dir),
                    "inspect": disclosure_cmd(f"ecc metrics {token} --json", project, ctx.run_id),
                }
            )

    if has_corrupt:
        return CommandResult.err(records)
    return CommandResult.ok(records)


def artifacts(command_input: StepInspectInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspection.artifacts import discover_artifacts

    step_token = command_input.step
    project = ctx.project

    artifact_records, rc = discover_artifacts(
        ctx.run_dir,
        step_token,
        project,
        ctx.run_id,
        ctx.project_dir,
    )

    if rc != 0:
        if artifact_records and artifact_records[0].get("status") == "unknown_step":
            return CommandResult.err(
                [
                    {
                        "step": artifact_records[0]["step"],
                        "status": "unknown_step",
                        "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                    }
                ]
            )
        return CommandResult.err(artifact_records)

    if not artifact_records:
        if step_token is not None:
            return CommandResult.ok(
                [
                    {
                        "step": step_token,
                        "artifacts_status": "none",
                        "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                        "log": disclosure_cmd(f"ecc log {step_token}", project, ctx.run_id),
                    }
                ]
            )
        return CommandResult.ok(
            [
                {
                    "artifacts_status": "none",
                    "workspace": ctx.run_dir,
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                }
            ]
        )

    records = []
    for artifact in artifact_records:
        line_fields = {
            "artifact": os.path.basename(artifact["path"]),
            "step": artifact["step"],
            "role": artifact["role"],
            "path": artifact["path"],
            "inspect": disclosure_cmd(
                f"ecc artifacts {artifact['step']} --json",
                project,
                ctx.run_id,
            ),
        }
        if artifact["role"] == "analysis":
            line_fields["metrics"] = disclosure_cmd(
                f"ecc metrics {artifact['step']}",
                project,
                ctx.run_id,
            )
        if artifact["role"] == "log":
            line_fields["inspect"] = disclosure_cmd(
                f"ecc log {artifact['step']}",
                project,
                ctx.run_id,
            )
        if artifact["role"] in ("output", "report", "analysis", "log"):
            line_fields["config"] = disclosure_cmd(
                f"ecc config {artifact['step']} --resolved",
                project,
                ctx.run_id,
            )
        records.append(line_fields)
    return CommandResult.ok(records)


def config(command_input: ConfigInput, ctx: CommandContext) -> CommandResult:
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
                    "artifacts": first.get("artifacts"),
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


def diagnose(command_input: DiagnoseInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.inspection.diagnose import build_diagnose_issues

    step_token = command_input.step
    project = ctx.project
    display_run = ctx.run_id or "default"

    issues, _ = build_diagnose_issues(ctx.run_dir, step_token, project, ctx.run_id)

    if not issues:
        return CommandResult.ok(
            [
                {
                    "status": "clean",
                    "run": display_run,
                    "inspect_cmd": disclosure_cmd("ecc status", project, ctx.run_id),
                    "artifacts": disclosure_cmd("ecc artifacts", project, ctx.run_id),
                    "config": disclosure_cmd("ecc config --resolved", project, ctx.run_id),
                }
            ]
        )

    has_error = any(i.get("severity") == "error" for i in issues)
    text_keys = (
        "issue",
        "severity",
        "run",
        "step",
        "status",
        "count",
        "evidence",
        "log",
        "artifacts",
        "config",
        "start_cmd",
    )
    records = []
    for issue in issues:
        records.append({k: issue[k] for k in text_keys if k in issue})

    if has_error:
        return CommandResult.err(records)
    return CommandResult.ok(records)
