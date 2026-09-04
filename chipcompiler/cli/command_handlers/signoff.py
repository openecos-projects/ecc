import os

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult


def _resolve_workspace(command_input, ctx: CommandContext):
    """Return (workspace, None) or (None, error CommandResult)."""
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
            "report": disclosure_cmd("ecc report summary", project, ctx.run_id),
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
