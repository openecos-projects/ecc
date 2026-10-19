import sys

from rich.console import Console
from rich.table import Table

from chipcompiler.cli.core.line_records import serialize_line_records
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.rendering.pretty import render_error


def _cell(step: dict) -> str:
    checker = step["checker"]
    if checker is None:
        return step["state"]
    counts = checker["counts"]
    if counts:
        if checker["violation_count"] is not None:
            detail = str(checker["violation_count"])
        else:
            detail = ", ".join(
                f"{key.removeprefix('sta_').removesuffix('_violation_count')}={value}"
                for key, value in counts.items()
            )
        return f"{step['state']}; {checker['verdict']} ({detail})"
    detail = "N/A" if checker["availability"] == "not_applicable" else checker["verdict"]
    return f"{step['state']}; {detail}"


def render_project_text(
    result: CommandResult, ctx: CommandContext, command_input, *, color: bool
) -> None:
    if result.exit_code:
        render_error(result.records, color=color)
        return
    report = result.records[0]
    table = Table(title=f"Project workspace report: {report['design']}", box=None)
    for label in ("Rank", "Workspace", "QoR", "Flow", "Manifest"):
        table.add_column(label)
    for column in report["columns"]:
        table.add_column(f"{column['token']}\n{column['tool']}")
    for row in report["workspaces"]:
        cells = {(step["step"], step["tool"]): step for step in row["steps"]}
        missing_cell = (
            "unknown" if row["flow_status"] in {"missing", "invalid", "oversized"} else "N/A"
        )
        score = row["qor"]["score"]
        table.add_row(
            str(row["rank"]) if row["rank"] is not None else "—",
            row["workspace_id"],
            f"{score:.2f}" if score is not None else f"— ({row['qor']['availability']})",
            row["flow_status"],
            row["manifest_status"],
            *[
                _cell(cells[(column["step"], column["tool"])])
                if (column["step"], column["tool"]) in cells
                else missing_cell
                for column in report["columns"]
            ],
        )
    console = Console(
        file=sys.stdout,
        force_terminal=color,
        no_color=not color,
        markup=False,
        highlight=False,
        width=max(100, 45 + 22 * len(report["columns"])),
    )
    console.print(table)
    for warning in report["warnings"]:
        console.print(f"Warning: {warning}", markup=False)


def render_project_plain(
    result: CommandResult, ctx: CommandContext, command_input, *, color: bool
) -> None:
    if result.exit_code:
        from chipcompiler.cli.rendering.render import render_plain

        render_plain(result.records)
        return
    report = result.records[0]
    records = [
        {
            "record": "project_report",
            "project": report["project"],
            "status": report["status"],
            "workspaces": len(report["workspaces"]),
        }
    ]
    for index, column in enumerate(report["columns"], start=1):
        records.append({"record": "step_column", "index": index, **column})
    for row in report["workspaces"]:
        records.append(
            {
                "record": "workspace",
                "workspace_id": row["workspace_id"],
                "rank": row["rank"],
                "qor_score": row["qor"]["score"],
                "qor_availability": row["qor"]["availability"],
                "qor_profile": row["qor"]["profile"],
                "qor_scalar_status": row["qor"]["scalar_status"],
                "provisional": row["qor"]["provisional"],
                "flow_status": row["flow_status"],
                "manifest_status": row["manifest_status"],
                "source": row["qor"]["source"],
            }
        )
        for step in row["steps"]:
            checker = step["checker"]
            records.append(
                {
                    "record": "workspace_step",
                    "workspace_id": row["workspace_id"],
                    "step": step["step"],
                    "tool": step["tool"],
                    "state": step["state"],
                    "category": step["category"],
                    "verdict": checker["verdict"] if checker else None,
                    "availability": checker["availability"] if checker else None,
                    "has_violations": checker["has_violations"] if checker else None,
                    "violation_count": checker["violation_count"] if checker else None,
                    "source": checker["source"] if checker else None,
                }
            )
            for metric, count in checker["counts"].items() if checker else ():
                records.append(
                    {
                        "record": "checker_count",
                        "workspace_id": row["workspace_id"],
                        "step": step["step"],
                        "tool": step["tool"],
                        "metric": metric,
                        "count": count,
                    }
                )
    for warning in report["warnings"]:
        records.append({"record": "warning", "reason": warning})
    print(serialize_line_records(records), end="")
