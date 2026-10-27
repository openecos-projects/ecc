from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.core.version_info import build_identity, ecc_version
from chipcompiler.update_check import INSTALLER_URLS, check_for_update


def check_update(command_input, ctx: CommandContext) -> CommandResult:
    build_commit, build_date = build_identity()
    result = check_for_update(ecc_version(), build_commit, build_date)
    latest = None
    if result.latest is not None:
        latest = {
            "tag": result.latest.tag,
            "date": str(result.latest.date),
            "ecc_version": result.latest.ecc_version,
            "ecc_commit": result.latest.ecc_commit,
        }
    record = {
        "schema_version": 1,
        "status": result.status,
        "current_version": result.current_version,
        "current_commit": result.current_commit,
        "current_build_date": result.current_build_date,
        "latest": latest,
        "installer_urls": list(INSTALLER_URLS),
        "inspect_cmd": disclosure_cmd("ecc version"),
    }
    return CommandResult.ok([record])
