from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.engine.workspace_spec import describe_workspace_spec


def flow_list(_args, _ctx: CommandContext) -> CommandResult:
    return _flow_records(describe_workspace_spec()["flowDefinitions"])


def flow_show(args, _ctx: CommandContext) -> CommandResult:
    flows = describe_workspace_spec()["flowDefinitions"]
    selected = [flow for flow in flows if flow["flowId"] == args.flow_id]
    if not selected:
        return CommandResult.err(
            [error_record("unknown_flow", flow_id=args.flow_id)],
            exit_code=2,
        )
    return _flow_records(selected)


def flow_validate(args, _ctx: CommandContext) -> CommandResult:
    flows = describe_workspace_spec()["flowDefinitions"]
    if args.flow_id is not None:
        flows = [flow for flow in flows if flow["flowId"] == args.flow_id]
        if not flows:
            return CommandResult.err(
                [error_record("unknown_flow", flow_id=args.flow_id)],
                exit_code=2,
            )
    result = _flow_records(flows)
    if result.exit_code:
        return result
    return CommandResult.ok(
        [
            {
                "record": "flow_validation",
                "status": "valid",
                "flow_id": flow["flowId"],
                "step_count": len(flow["stepIds"]),
            }
            for flow in flows
        ]
    )


def _flow_records(flows: list[dict]) -> CommandResult:
    records = []
    for flow in flows:
        if not flow["stepIds"]:
            return CommandResult.err(
                [
                    error_record(
                        "invalid_flow",
                        flow_id=flow["flowId"],
                        reason="registered flow has no steps",
                    )
                ],
                exit_code=1,
            )
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
