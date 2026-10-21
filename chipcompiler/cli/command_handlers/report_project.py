from chipcompiler.cli.core.project_report_inputs import ReportProjectInput
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.project_matrix import build_project_matrix
from chipcompiler.project.manifest import ManifestError, load_manifest


def project(command_input: ReportProjectInput, ctx: CommandContext) -> CommandResult:
    if ctx.config_error:
        return CommandResult.err([error_record("config_error", reason=ctx.config_error)])
    try:
        manifest = load_manifest(ctx.project_dir)
    except ManifestError as exc:
        return CommandResult.err([error_record("manifest_invalid", reason=str(exc))])
    return CommandResult.ok([build_project_matrix(manifest)])
