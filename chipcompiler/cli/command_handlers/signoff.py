import os
import shlex

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def _resolve_workspace(command_input, ctx: CommandContext):
    """Return (workspace, None) or (None, error CommandResult)."""
    from chipcompiler.data import load_workspace

    project = ctx.project

    if command_input.workspace is not None:
        if project is not None or command_input.project.run_id is not None:
            return None, CommandResult.err([error_record("project_workspace_conflict")])
        path = os.path.abspath(os.path.expanduser(command_input.workspace))
        try:
            workspace = load_workspace(path)
        except Exception as exc:
            return None, CommandResult.err(
                [error_record("invalid_workspace", workspace=path, reason=str(exc))]
            )
        if workspace is None:
            return None, CommandResult.err([error_record("invalid_workspace", workspace=path)])
        return workspace, None

    if not os.path.isdir(ctx.run_dir):
        return None, CommandResult.err(
            [
                error_record(
                    "missing_workspace",
                    run_dir=ctx.run_dir,
                    run=disclosure_cmd("ecc run", project, ctx.run_id),
                )
            ]
        )
    try:
        workspace = load_workspace(ctx.run_dir)
    except Exception as exc:
        return None, CommandResult.err(
            [error_record("invalid_workspace", workspace=ctx.run_dir, reason=str(exc))]
        )
    if workspace is None:
        return None, CommandResult.err([error_record("invalid_workspace", workspace=ctx.run_dir)])
    return workspace, None


def _workspace_display(command_input, ctx: CommandContext) -> str:
    if command_input.workspace is not None:
        return os.path.abspath(os.path.expanduser(command_input.workspace))
    return ctx.run_dir


def inspect(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve_workspace(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.runtime.signoff_export import inspect_signoff_package

    review = inspect_signoff_package(workspace)
    project = ctx.project
    records = [
        {
            "signoff": "inspect",
            "status": review.get("status", "blocked"),
            "workspace": _workspace_display(command_input, ctx),
            "export": disclosure_cmd("ecc signoff export -o <path>", project, ctx.run_id),
            "report": disclosure_cmd("ecc signoff report", project, ctx.run_id),
        }
    ]
    for group in review.get("groups", []):
        records.append(
            {
                "group": group.get("id", ""),
                "label": group.get("label", ""),
                "status": group.get("status", ""),
                "available": group.get("available"),
                "expected": group.get("expected"),
                "summary": group.get("summary"),
            }
        )
    for risk in review.get("risks", []):
        record = {
            "risk": risk.get("severity", ""),
            "title": risk.get("title", ""),
            "summary": risk.get("summary", ""),
        }
        details = risk.get("details") or []
        if details:
            first = details[0]
            record["location"] = first.get("location", "")
            record["reason"] = first.get("reason", "")
            record["detail_count"] = len(details)
        records.append(record)

    # Inspection is advisory: blocked readiness is data, not a command failure.
    return CommandResult.ok(records)


def export(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve_workspace(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.runtime.workspace_api import RuntimeApiError

    try:
        from chipcompiler.runtime.signoff_export import export_signoff_package_archive

        output_path = export_signoff_package_archive(
            workspace,
            command_input.output_path,
            include_debug=command_input.include_debug,
        )
    except RuntimeApiError as exc:
        return CommandResult.err(
            [
                error_record(
                    "signoff_incomplete",
                    reason=str(exc),
                    inspect=disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
                )
            ]
        )
    return CommandResult.ok(
        [
            {
                "signoff": "export",
                "status": "exported",
                "path": output_path,
                "inspect_cmd": disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
            }
        ]
    )


def _design_name(workspace) -> str:
    design = getattr(workspace, "design", None)
    name = getattr(design, "name", "") if design is not None else ""
    if name:
        return name
    from chipcompiler.utility.json import json_read

    parameters = json_read(os.path.join(workspace.directory or "", "home", "parameters.json"))
    return parameters.get("Design") or "design"


def report(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = _resolve_workspace(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.engine.signoff import generate_text_report

    try:
        content = generate_text_report(workspace)
    except Exception as exc:
        return CommandResult.err([error_record("report_failed", reason=str(exc))])

    design = _design_name(workspace)
    workspace_display = _workspace_display(command_input, ctx)
    if command_input.output_path is not None:
        destination = os.path.abspath(os.path.expanduser(command_input.output_path))
    else:
        destination = os.path.join(workspace_display, "signoff", f"{design}_design_summary.txt")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    data = content.encode("utf-8")
    with open(destination, "wb") as f:
        f.write(data)

    return CommandResult.ok(
        [
            {
                "signoff": "report",
                "status": "written",
                "path": destination,
                "design": design,
                "bytes": len(data),
                "view": f"cat {shlex.quote(destination)}",
            }
        ]
    )


# ---------------------------------------------------------------------------
# TEXT rendering for `ecc signoff inspect`
# ---------------------------------------------------------------------------


def render_signoff_inspect_text(records) -> None:
    summary = records[0]
    print("[signoff]")
    print(f"  status    : {summary['status']}")
    print(f"  workspace : {summary['workspace']}")
    print(f"  export    : {summary['export']}")
    print(f"  report    : {summary['report']}")
    groups = [r for r in records[1:] if "group" in r]
    if groups:
        print()
        print("  groups:")
        for group in groups:
            counts = ""
            if group.get("available") is not None:
                counts = f"  ({group['available']}/{group['expected']})"
            print(f"    {group['group']:14s} {group['status']:9s}{counts}")
    risks = [r for r in records[1:] if "risk" in r]
    if risks:
        print()
        print("  risks:")
        for risk in risks:
            print(f"    [{risk['risk']:7s}] {risk['title']}")
            if risk.get("reason"):
                print(f"              {risk['reason']}")
