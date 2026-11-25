"""Project the execution plan of a Workspace's recorded flow."""

from pathlib import Path

from chipcompiler.cli.core.records import error_record, manifest_error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import read_flow_json
from chipcompiler.cli.project.config import resolve_max_parallel_steps
from chipcompiler.data.flow.needs import plan_needs
from chipcompiler.data.flow.plan import PlannedStep
from chipcompiler.data.flow.policy import (
    FlowInputResolver,
    FlowInputStepError,
    analysis_wave_end,
)
from chipcompiler.data.types import inserted_step_kind


def workspace_plan(_args, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    if ctx.config_error:
        return CommandResult.err([error_record("config_error", reason=ctx.config_error)])
    data = read_flow_json(ctx.run_dir)
    if not isinstance(data, dict) or not data.get("steps"):
        return CommandResult.err(
            [error_record("workspace_flow_unavailable", workspace=ctx.run_dir)]
        )
    try:
        rows = plan_records(data["steps"])
        limit = resolve_max_parallel_steps(ctx.config)
    except (ValueError, FlowInputStepError) as exc:
        return CommandResult.err([error_record("workspace_flow_invalid", reason=str(exc))])
    return CommandResult.ok(
        [
            {
                "record": "workspace_flow",
                "workspace_id": ctx.run_id or Path(ctx.run_dir).name,
                "max_parallel_steps": limit,
            },
            *rows,
        ]
    )


def plan_records(records: list[dict]) -> list[dict]:
    if not isinstance(records, list):
        raise ValueError("Workspace flow steps must be a list")
    validated_steps = []
    for row in records:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or not isinstance(row.get("tool"), str)
            or not row["tool"]
        ):
            raise ValueError("Invalid step record in Workspace flow ledger")
        validated_steps.append(
            PlannedStep(
                name=row["name"],
                tool=row["tool"],
                enabled=True,
                optional=False,
                inserted=inserted_step_kind(row["name"]) is not None,
            )
        )
    steps = tuple(validated_steps)
    needs = plan_needs(steps)
    resolver = FlowInputResolver(records)
    stage, end = 0, 0
    rows = []
    for index, step in enumerate(steps):
        if index == end:
            stage += 1
            end = analysis_wave_end(records, index)
        rows.append(
            {
                "record": "flow_step",
                "step": step.name,
                "tool": step.tool,
                "stage": stage,
                "needs": dict(needs[index].producers),
                "design_source": resolver.input_step_name(index),
            }
        )
    return rows
