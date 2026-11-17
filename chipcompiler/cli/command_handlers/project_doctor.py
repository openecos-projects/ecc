"""Handler for ``ecc project doctor``: project.json ↔ directory consistency.

Report mode is read-only and exits 1 when inconsistencies are found (the
same "required failure" semantics as ``ecc doctor``). ``--fix`` repairs
every finding explicitly and exits 1 only when a repair failed; each
repair is emitted as a record for audit.

A project directory that was renamed, moved or copied is reported as
``moved-project`` before anything else: no other check can run until
``--fix`` has re-anchored the project to its directory.
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
    from chipcompiler.project.consistency import (
        MOVED_PROJECT,
        find_inconsistencies,
        find_relocation,
        relocate_project,
        repair_findings,
    )

    relocated: list[dict] = []
    relocation = find_relocation(ctx.project_dir)
    if relocation is not None:
        record = {
            "check": MOVED_PROJECT,
            "status": "fail",
            "recorded_root": relocation.recorded_root,
            "project": relocation.project_dir,
            "workspaces": [workspace_id for workspace_id, _path in relocation.workspaces],
            "detail": "project.json records another directory: "
            "the project was renamed, moved or copied",
        }
        summary = {"doctor": "project", "status": "failed", "checked": 0, "inconsistent": 1}
        if not command_input.fix:
            record["remediation"] = disclosure_cmd("ecc project doctor --fix", ctx.project)
            return CommandResult.err([summary, record])
        failure = relocate_project(relocation)
        if failure is not None:
            record.update(fix="failed", fix_detail=failure)
            return CommandResult.err([{**summary, "fixed": 0}, record])
        record["fix"] = "relocated"
        relocated.append(record)

    try:
        manifest = load_manifest(ctx.project_dir)
    except ManifestError as exc:
        return CommandResult.err([*relocated, error_record("manifest_invalid", reason=str(exc))])

    findings = find_inconsistencies(manifest)
    if command_input.fix and (findings or relocated):
        actions = repair_findings(manifest, findings)
        failed = [action for action in actions if action.action == "failed"]
        records = [
            {
                "doctor": "project",
                "status": "failed" if failed else "fixed",
                "checked": len(manifest.workspaces),
                "inconsistent": len(findings) + len(relocated),
                "fixed": len(actions) - len(failed) + len(relocated),
            }
        ]
        records.extend(relocated)
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
