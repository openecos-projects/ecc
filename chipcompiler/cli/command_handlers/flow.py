from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.engine.workspace_spec import describe_workspace_spec


def flow_list(_args, _ctx: CommandContext) -> CommandResult:
    records = []
    for flow in describe_workspace_spec()["flowDefinitions"]:
        skippable = set(flow["skippableStepIds"])
        default_skipped = set(flow["defaultSkippedStepIds"])
        for ordinal, step_id in enumerate(flow["stepIds"]):
            records.append(
                {
                    "record": "flow_step",
                    "flow_id": flow["flowId"],
                    "step_id": step_id,
                    "ordinal": ordinal,
                    "skippable": step_id in skippable,
                    "default_skipped": step_id in default_skipped,
                }
            )
    return CommandResult.ok(records)
