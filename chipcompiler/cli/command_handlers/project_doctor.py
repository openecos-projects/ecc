"""Handler for ``ecc project doctor``: project.json ↔ directory consistency.

Report mode is read-only and exits 1 when inconsistencies are found (the
same "required failure" semantics as ``ecc doctor``). ``--fix`` repairs
every finding explicitly and exits 1 only when a repair failed; each
repair is emitted as a record for audit.
"""

import os

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.project.manifest import MANIFEST_FILENAME, ManifestError, load_manifest


def project_doctor(command_input, ctx: CommandContext) -> CommandResult:
    if ctx.project_state != "manifest":
        return CommandResult.err(
            [
                error_record(
                    "missing_manifest",
                    path=os.path.join(ctx.project_dir, MANIFEST_FILENAME),
                    reason="project doctor checks project.json against workspace directories",
                )
            ]
        )
    from chipcompiler.project.consistency import find_inconsistencies, repair_findings

    try:
        manifest = load_manifest(ctx.project_dir)
    except ManifestError as exc:
        return CommandResult.err([error_record("manifest_invalid", reason=str(exc))])

    findings = find_inconsistencies(manifest)
    if command_input.fix and findings:
        actions = repair_findings(manifest, findings)
        failed = [action for action in actions if action.action == "failed"]
        records = [
            {
                "doctor": "project",
                "status": "failed" if failed else "fixed",
                "checked": len(manifest.workspaces),
                "inconsistent": len(findings),
                "fixed": len(actions) - len(failed),
            }
        ]
        records.extend(_finding_record(action.finding, ctx, action=action) for action in actions)
        if failed:
            return CommandResult.err(records)
        return CommandResult.ok(records)

    records = [
        {
            "doctor": "project",
            "status": "failed" if findings else "ok",
            "checked": len(manifest.workspaces),
            "inconsistent": len(findings),
        }
    ]
    records.extend(_finding_record(finding, ctx) for finding in findings)
    if findings:
        return CommandResult.err(records)
    return CommandResult.ok(records)


def _finding_record(finding, ctx: CommandContext, action=None) -> dict:
    record = {
        "check": finding.check,
        "status": "fail",
        "workspace_id": finding.workspace_id,
        "workspace": finding.workspace_path,
        "detail": finding.detail,
    }
    if action is None:
        record["remediation"] = disclosure_cmd("ecc project doctor --fix", ctx.project)
    else:
        record["fix"] = action.action
        if action.detail:
            record["fix_detail"] = action.detail
    return record
