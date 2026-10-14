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
from ecc_experience.cli.inputs import (
    CampaignInput,
    CollectInput,
    EvaluationInput,
    PlanInput,
    RecommendInput,
    RecordingInput,
    ReleaseInput,
    StoreInput,
)
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
            "experience_store_required": EXIT_USAGE_ERROR,
            "experience_project_invalid": EXIT_USAGE_ERROR,
            "experience_not_configured": EXIT_USAGE_ERROR,
            "experience_manifest_invalid": EXIT_USAGE_ERROR,
            "experience_manifest_input_missing": EXIT_USAGE_ERROR,
            "experience_campaign_design_invalid": EXIT_USAGE_ERROR,
            "experience_campaign_trial_invalid": EXIT_USAGE_ERROR,
            "experience_campaign_ledger_invalid": EXIT_USAGE_ERROR,
            "experience_campaign_ledger_missing": EXIT_USAGE_ERROR,
            "experience_campaign_manifest_changed": EXIT_REVISION_CONFLICT,
            "experience_campaign_trial_conflict": EXIT_REVISION_CONFLICT,
            "experience_plan_invalid": EXIT_USAGE_ERROR,
            "experience_release_invalid": EXIT_USAGE_ERROR,
            "experience_release_unverified": EXIT_GATE_FAILED,
            "experience_release_conflict": EXIT_REVISION_CONFLICT,
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


def recommend(command_input: RecommendInput, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])

    def operation() -> CommandResult:
        from ecc_experience.api import recommend as recommend_cases

        result = recommend_cases(
            ctx.run_dir,
            command_input.store,
            limit=command_input.limit,
            release=command_input.release,
        )
        return CommandResult.ok([{"experience": "recommend", **result}])

    return _guard(operation)


def plan(command_input: PlanInput, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])

    def operation() -> CommandResult:
        from ecc_experience.api import plan as build_optimization_plan

        result = build_optimization_plan(
            ctx.run_dir,
            command_input.store,
            command_input.output_path,
            limit=command_input.limit,
            release=command_input.release,
        )
        return CommandResult.ok([{"experience": "plan", **result}])

    return _guard(operation)


def evaluate(command_input: EvaluationInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import evaluate as evaluate_cases

        result = evaluate_cases(
            command_input.baseline, command_input.candidate, command_input.store
        )
        return CommandResult.ok([{"experience": "evaluate", **result}])

    return _guard(operation)


def release_create(command_input: ReleaseInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import release_create as create

        if not command_input.case_ids:
            raise ExperienceError(
                "At least one --case-id is required", code="experience_release_invalid"
            )
        result = create(
            command_input.case_ids, command_input.store, command_input.output_path or ""
        )
        return CommandResult.ok([{"experience": "release_create", **result}])

    return _guard(operation)


def release_verify(command_input: ReleaseInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import release_verify as verify

        if command_input.release_path is None:
            raise ExperienceError("Release path is required", code="experience_release_invalid")
        result = verify(command_input.release_path, command_input.store)
        return CommandResult.ok([{"experience": "release_verify", **result}])

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


def enable(command_input: RecordingInput, ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import enable as enable_recording

        if not command_input.store:
            raise ExperienceError("--store is required", code="experience_store_required")
        config = enable_recording(ctx.project_dir, command_input.store)
        return CommandResult.ok(
            [
                {
                    "experience": "enable",
                    "enabled": config.enabled,
                    "mode": config.mode,
                    "store": config.store,
                }
            ]
        )

    return _guard(operation)


def status(command_input: RecordingInput, ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import status as recording_status

        return CommandResult.ok([{"experience": "status", **recording_status(ctx.project_dir)}])

    return _guard(operation)


def disable(command_input: RecordingInput, ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import disable as disable_recording

        config = disable_recording(ctx.project_dir)
        return CommandResult.ok(
            [
                {
                    "experience": "disable",
                    "enabled": config.enabled,
                    "mode": config.mode,
                    "store": config.store,
                }
            ]
        )

    return _guard(operation)


def drain(command_input: RecordingInput, ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import drain as drain_recording

        return CommandResult.ok(
            [
                {
                    "experience": "drain",
                    "project": ctx.project_dir,
                    "attempts": drain_recording(ctx.project_dir, limit=command_input.limit),
                }
            ]
        )

    return _guard(operation)


def validate_campaign(command_input: CampaignInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import validate_campaign as validate

        return CommandResult.ok(
            [{"experience": "campaign_validate", **validate(command_input.manifest)}]
        )

    return _guard(operation)


def init_campaign(command_input: CampaignInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import init_campaign as initialize

        result = initialize(command_input.manifest, command_input.ledger)
        return CommandResult.ok([{"experience": "campaign_init", **result}])

    return _guard(operation)


def record_campaign_trial(command_input: CampaignInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import record_trial

        if not command_input.ledger or not command_input.design_id or not command_input.workspace:
            raise ExperienceError(
                "--ledger, --design and --workspace are required",
                code="experience_campaign_trial_invalid",
            )
        if not command_input.status:
            raise ExperienceError("--status is required", code="experience_campaign_trial_invalid")
        result = record_trial(
            command_input.ledger,
            design_id=command_input.design_id,
            workspace=command_input.workspace,
            status=command_input.status,
            trial_id=command_input.trial_id,
            case_id=command_input.case_id,
            reason=command_input.reason,
        )
        return CommandResult.ok([{"experience": "campaign_record", **result}])

    return _guard(operation)


def campaign_status(command_input: CampaignInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import campaign_status as read_status

        return CommandResult.ok(
            [
                {
                    "experience": "campaign_status",
                    **read_status(command_input.manifest, command_input.ledger),
                }
            ]
        )

    return _guard(operation)


def campaign_summary(command_input: CampaignInput, _ctx: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import campaign_summary as summarize

        return CommandResult.ok(
            [
                {
                    "experience": "campaign_summary",
                    **summarize(command_input.manifest, command_input.ledger),
                }
            ]
        )

    return _guard(operation)
