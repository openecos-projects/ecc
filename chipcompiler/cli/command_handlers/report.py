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
