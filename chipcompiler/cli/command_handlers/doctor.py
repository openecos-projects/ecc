from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection import env_probe


def doctor(command_input, ctx: CommandContext) -> CommandResult:
    results = env_probe.probe_environment(env_probe.ALL_COMPONENTS, cfg=ctx.config)

    failed = [r for r in results if r.status == env_probe.FAIL]
    failed_required = [r for r in failed if r.required]
    failed_optional = [r for r in failed if not r.required]
    if failed_required:
        status = "failed"
    elif failed_optional:
        status = "attention"
    else:
        status = "ok"

    # `failed` counts only required failures (the ones that block `ecc run`);
    # optional failures are surfaced separately as `attention` so the summary
    # never reads worse than the exit status suggests.
    records = [
        {
            "doctor": "environment",
            "status": status,
            "checked": len(results),
            "failed": len(failed_required),
            "attention": len(failed_optional),
            "run": disclosure_cmd("ecc run", ctx.project),
        }
    ]
    for result in results:
        record = {
            "component": result.component,
            "status": result.status,
            "required": result.required,
        }
        if result.detail:
            record["detail"] = result.detail
        if result.status == env_probe.FAIL and result.remediation:
            record["remediation"] = result.remediation
        records.append(record)

    if failed_required:
        return CommandResult.err(records)
    return CommandResult.ok(records)
