import pathlib

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.core.version_info import ecc_version
from chipcompiler.cli.inspection import env_probe


def _ecc_install_path() -> str:
    import chipcompiler

    return str(pathlib.Path(chipcompiler.__file__).resolve().parent)


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
    ecc_install_path = _ecc_install_path()
    summary = {
        "doctor": "environment",
        "status": status,
        "checked": len(results),
        "failed": len(failed_required),
        "attention": len(failed_optional),
        "detail": f"ecc {ecc_version()} at {ecc_install_path}",
        "run": disclosure_cmd("ecc run", ctx.project),
    }
    ecc_installed_at = env_probe.installed_at_for_path(ecc_install_path)
    if ecc_installed_at:
        summary["installed_at"] = ecc_installed_at
    records = [summary]
    for result in results:
        record = {
            "component": result.component,
            "status": result.status,
            "required": result.required,
        }
        if result.detail:
            record["detail"] = result.detail
        if result.installed_at:
            record["installed_at"] = result.installed_at
        if result.status == env_probe.FAIL and result.remediation:
            record["remediation"] = result.remediation
        records.append(record)

    if failed_required:
        return CommandResult.err(records)
    return CommandResult.ok(records)
