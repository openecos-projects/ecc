from collections.abc import Callable

from chipcompiler.cli.core.exit_codes import (
    EXIT_GATE_FAILED,
    EXIT_GATE_UNKNOWN,
    EXIT_REVISION_CONFLICT,
    EXIT_USAGE_ERROR,
    EXIT_WORKSPACE_BUSY,
)
from chipcompiler.cli.core.records import error_record, manifest_error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli.inputs import CollectInput, StoreInput
from ecc_experience.models import ExperienceError


def _guard(operation: Callable[[], CommandResult]) -> CommandResult:
    try:
        return operation()
    except ExperienceError as exc:
        codes = {
            "experience_workspace_busy": EXIT_WORKSPACE_BUSY,
            "experience_store_busy": EXIT_WORKSPACE_BUSY,
            "experience_source_changed": EXIT_REVISION_CONFLICT,
            "experience_case_conflict": EXIT_REVISION_CONFLICT,
            "experience_case_id_invalid": EXIT_USAGE_ERROR,
        }
        return CommandResult.err([error_record(exc.code, reason=str(exc))], codes.get(exc.code, 1))
    except OSError as exc:
        return CommandResult.err([error_record("experience_io_failed", reason=str(exc))])


def collect(command_input: CollectInput, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])

    def operation() -> CommandResult:
        from ecc_experience.api import collect as collect_case

        result = collect_case(ctx.run_dir, command_input.store)
        return CommandResult.ok(
            [
                {
                    "experience": "collect",
                    "case_id": result.case.case_id,
                    "status": result.status,
                    "store": command_input.store,
                    "source": result.case.source.model_dump(),
                    "validation_scope": result.case.validation_scope,
                    "limitations": result.case.limitations,
                }
            ]
        )

    return _guard(operation)


def list_cases(command_input: StoreInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import list_cases as read_cases

        cases = read_cases(command_input.store)
        return CommandResult.ok(
            [
                {
                    "experience": "list",
                    "case_id": case.case_id,
                    "source": case.source.model_dump(),
                    "collected_at": case.collected_at,
                    "validation_scope": case.validation_scope,
                }
                for case in cases
            ]
        )

    return _guard(operation)


def show(command_input: StoreInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import show as read_case

        if command_input.case_id is None:
            raise ExperienceError("Case ID is required", code="experience_case_id_invalid")
        return CommandResult.ok(
            [
                {
                    "experience": "show",
                    **read_case(command_input.case_id, command_input.store).model_dump(),
                }
            ]
        )

    return _guard(operation)


def verify(command_input: StoreInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import verify as verify_case
        from ecc_experience.knowledge.store import ExperienceStore

        if command_input.case_id is not None:
            ExperienceStore(command_input.store).case_directory(command_input.case_id)
        ids = (
            [command_input.case_id]
            if command_input.case_id
            else ExperienceStore(command_input.store).list_ids()
        )
        records = []
        for case_id in ids:
            try:
                result = verify_case(case_id, command_input.store).model_dump()
            except (ExperienceError, OSError) as exc:
                result = {
                    "case_id": case_id,
                    "status": "fail",
                    "integrity": "fail",
                    "findings": [{"status": "fail", "check": "case_read", "reason": str(exc)}],
                }
            records.append({"experience": "verify", **result})
        if not records:
            records.append(
                {"experience": "verify", "status": "unknown", "reason": "Store is empty"}
            )
        statuses = {record["status"] for record in records}
        exit_code = (
            EXIT_GATE_FAILED
            if "fail" in statuses
            else EXIT_GATE_UNKNOWN
            if "unknown" in statuses
            else 0
        )
        return CommandResult(records=tuple(records), exit_code=exit_code)

    return _guard(operation)
