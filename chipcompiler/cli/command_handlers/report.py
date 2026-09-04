"""Handlers for the `ecc report` command group (workspace-level reports)."""

import os
import shlex

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def _resolve(command_input, ctx: CommandContext):
    from chipcompiler.cli.inspection.discovery import resolve_command_workspace

    workspace, error = resolve_command_workspace(
        command_input.workspace, ctx.project, command_input.project.run_id, ctx.run_dir
    )
    if error is not None:
        return None, CommandResult.err([error])
    return workspace, None


def _workspace_display(command_input, ctx: CommandContext) -> str:
    if command_input.workspace is not None:
        return os.path.abspath(os.path.expanduser(command_input.workspace))
    return ctx.run_dir


def _write_report(report_name, default_filename, content, command_input, ctx, extra):
    """Write the report file (default: <workspace>/signoff/) and summarize."""
    workspace_display = _workspace_display(command_input, ctx)
    if command_input.output_path is not None:
        destination = os.path.abspath(os.path.expanduser(command_input.output_path))
    else:
        destination = os.path.join(workspace_display, "signoff", default_filename)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        f.write(content)
    record = {
        "report": report_name,
        "path": destination,
        "bytes": len(content.encode("utf-8")),
        "view": f"cat {shlex.quote(destination)}",
    }
    record.update(extra)
    record["status"] = "written"
    return CommandResult.ok([record])


def qor(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.engine.qor_report import build_qor_report, generate_qor_report

    try:
        report = build_qor_report(workspace)
        content = generate_qor_report(workspace)
    except Exception as exc:
        return CommandResult.err([error_record("report_failed", reason=str(exc))])

    return _write_report(
        "qor",
        f"{report.design or 'design'}_qor_report.txt",
        content,
        command_input,
        ctx,
        extra={
            "design": report.design,
            "overall_score": report.overall_score,
            "qor_status": report.status,
            "gate_status": report.gate_status,
            "dimensions": [
                {
                    "dimension": d.label,
                    "score": d.score,
                    "weight": d.weight,
                    "metrics": d.metric_count,
                }
                for d in report.dimension_scores
            ],
            "inspect": disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
        },
    )


def checklist(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.engine.signoff.report_checklist import (
        build_checklist_report,
        generate_checklist_report,
    )

    try:
        report = build_checklist_report(workspace)
        content = generate_checklist_report(workspace)
    except Exception as exc:
        return CommandResult.err([error_record("report_failed", reason=str(exc))])

    if not report.available:
        return CommandResult.err(
            [
                error_record(
                    "checklist_unavailable",
                    inspect=disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
                )
            ]
        )

    return _write_report(
        "checklist",
        "checklist_report.txt",
        content,
        command_input,
        ctx,
        extra={
            "checklist_status": report.status,
            "items": len(report.items),
            "blocked": len(report.blocked_items),
            "attention": len(report.attention_items),
            "summary_counts": report.summary,
            "inspect": disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
        },
    )


def _design_name(workspace) -> str:
    design = getattr(workspace, "design", None)
    name = getattr(design, "name", "") if design is not None else ""
    if name:
        return name

    parameters = getattr(getattr(workspace, "parameters", None), "data", None)
    if isinstance(parameters, dict):
        return parameters.get("design") or parameters.get("Design") or "design"

    from chipcompiler.utility.json import json_read

    parameters = json_read(os.path.join(workspace.directory or "", "home", "parameters.json"))
    return parameters.get("design") or parameters.get("Design") or "design"


def summary(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.engine.signoff import generate_text_report

    try:
        content = generate_text_report(workspace)
    except Exception as exc:
        return CommandResult.err([error_record("report_failed", reason=str(exc))])

    design = _design_name(workspace)
    return _write_report(
        "summary",
        f"{design}_design_summary.txt",
        content,
        command_input,
        ctx,
        extra={"design": design},
    )


def _resolve_workspace_dir(command_input, ctx: CommandContext):
    """Resolve the workspace directory without loading a Workspace.

    `report step` previews current artifacts only; load_workspace would
    migrate configs and append a workspace log file on every invocation.
    Error records match resolve_command_workspace's contract.
    """
    if command_input.workspace is not None:
        if ctx.project is not None or ctx.run_id is not None:
            return None, CommandResult.err([error_record("project_workspace_conflict")])
        path = os.path.abspath(os.path.expanduser(command_input.workspace))
        if not os.path.isdir(path):
            return None, CommandResult.err([error_record("invalid_workspace", workspace=path)])
        return path, None

    if not os.path.isdir(ctx.run_dir):
        return None, CommandResult.err(
            [
                error_record(
                    "missing_workspace",
                    run_dir=ctx.run_dir,
                    run=disclosure_cmd("ecc run", ctx.project, ctx.run_id),
                )
            ]
        )
    return ctx.run_dir, None


def step(command_input, ctx: CommandContext) -> CommandResult:
    workspace_dir, failure = _resolve_workspace_dir(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.cli.inspection.step_view import (
        SECTIONS,
        available_step_tokens,
        build_step_detail_records,
        build_step_overview_records,
    )

    invalid = [s for s in command_input.sections if s not in SECTIONS]
    if invalid:
        return CommandResult.err(
            [
                error_record(
                    "invalid_section",
                    reason=f"unknown section(s): {', '.join(invalid)}",
                    sections=list(SECTIONS),
                )
            ]
        )
    if command_input.sections and command_input.step is None:
        return CommandResult.err(
            [error_record("section_requires_step", reason="--section needs a step token")]
        )

    if command_input.step is None:
        return CommandResult.ok(build_step_overview_records(workspace_dir, ctx.project, ctx.run_id))

    records = build_step_detail_records(
        workspace_dir,
        command_input.step,
        command_input.sections or SECTIONS,
        ctx.project,
        ctx.run_id,
    )
    if records is None:
        return CommandResult.err(
            [
                error_record(
                    "unknown_step",
                    step=command_input.step,
                    available=available_step_tokens(workspace_dir),
                    inspect=disclosure_cmd("ecc report step", ctx.project, ctx.run_id),
                )
            ]
        )
    return CommandResult.ok(records)
