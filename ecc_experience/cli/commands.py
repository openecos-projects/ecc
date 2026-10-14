from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption, WorkspaceOption
from ecc_experience.cli import handlers
from ecc_experience.cli.inputs import (
    CampaignInput,
    CollectInput,
    EvaluationInput,
    MatchInput,
    OptimizeInput,
    PlanInput,
    RecommendInput,
    RecordingInput,
    ReleaseInput,
    StoreInput,
    TransferInput,
)

StoreOption = Annotated[str, typer.Option("--store", help="External experience store directory")]
CaseArgument = Annotated[str, typer.Argument(help="Experience case ID")]

experience_app = create_app(help="Collect, query and verify design experience evidence")
campaign_app = create_app(help="Run and inspect generic experience campaigns")
release_app = create_app(help="Freeze and verify evidence-backed experience releases")
experience_app.add_typer(campaign_app, name="campaign")
experience_app.add_typer(release_app, name="release")


@experience_app.command("collect", help="Collect a read-only observation from a workspace")
def collect_cmd(
    *,
    store: StoreOption,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = CollectInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        store=store,
    )
    execute_command("experience", command_input, handlers.collect)


@experience_app.command("list", help="List observations in an experience store")
def list_cmd(
    *,
    store: StoreOption,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = StoreInput(
        output=output_options(plain=plain, json_output=json_output), store=store
    )
    execute_command("experience", command_input, handlers.list_cases)


@experience_app.command("show", help="Show an experience case and its provenance")
def show_cmd(
    case_id: CaseArgument,
    *,
    store: StoreOption,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = StoreInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        case_id=case_id,
    )
    execute_command("experience", command_input, handlers.show)


@experience_app.command("verify", help="Verify stored evidence and source freshness")
def verify_cmd(
    case_id: Annotated[str | None, typer.Argument(help="Case ID; omit to verify the store")] = None,
    *,
    store: StoreOption,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = StoreInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        case_id=case_id,
    )
    execute_command("experience", command_input, handlers.verify)


@experience_app.command("features", help="Read digest-checked features through a flow step")
def features_cmd(
    case_id: CaseArgument,
    *,
    store: StoreOption,
    through_step: Annotated[
        str | None, typer.Option("--through-step", help="Last visible flow step")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = StoreInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        case_id=case_id,
        through_step=through_step,
    )
    execute_command("experience", command_input, handlers.features)


@experience_app.command("match", help="Explain compatible stage matches from a frozen release")
def match_cmd(
    case_id: CaseArgument,
    *,
    store: StoreOption,
    release: Annotated[str, typer.Option("--release", help="Frozen release JSON")],
    through_step: Annotated[str, typer.Option("--through-step", help="Last visible stage")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    experimental_cross_design: Annotated[bool, typer.Option("--experimental-cross-design")] = False,
    groups: Annotated[
        str | None, typer.Option("--groups", help="Explicit case-to-family groups JSON")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = MatchInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        case_id=case_id,
        release=release,
        through_step=through_step,
        limit=limit,
        experimental_cross_design=experimental_cross_design,
        groups=groups,
    )
    execute_command("experience", command_input, handlers.match)


@experience_app.command(
    "export", help="Export explicitly selected cases or a release with evidence"
)
def export_cmd(
    *,
    store: StoreOption,
    output: Annotated[str, typer.Option("--output", help="Experience package tar.gz")],
    case_ids: Annotated[list[str] | None, typer.Option("--case-id", help="Case to include")] = None,
    release: Annotated[
        str | None, typer.Option("--release", help="Release JSON to include")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = TransferInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        output_path=output,
        case_ids=case_ids,
        release_path=release,
    )
    execute_command("experience", command_input, handlers.package_export)


@experience_app.command(
    "import", help="Validate and merge an experience package without overwriting"
)
def import_cmd(
    *,
    store: StoreOption,
    package: Annotated[str, typer.Option("--package", help="Experience package tar.gz")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = TransferInput(
        output=output_options(plain=plain, json_output=json_output),
        store=store,
        package_path=package,
    )
    execute_command("experience", command_input, handlers.package_import)


@experience_app.command("enable", help="Enable non-invasive execution fact recording")
def enable_cmd(
    *,
    store: StoreOption,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecordingInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        store=store,
    )
    execute_command("experience", command_input, handlers.enable)


@experience_app.command("status", help="Show project experience recording status")
def status_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecordingInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
    )
    execute_command("experience", command_input, handlers.status)


@experience_app.command("disable", help="Disable execution fact recording")
def disable_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecordingInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
    )
    execute_command("experience", command_input, handlers.disable)


@experience_app.command("drain", help="Recover completed recorded attempts into the store")
def drain_cmd(
    *,
    project: ProjectOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 32,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecordingInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        limit=limit,
    )
    execute_command("experience", command_input, handlers.drain)


@experience_app.command("recommend", help="Show conservative observed configurations")
def recommend_cmd(
    *,
    store: StoreOption,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    release: Annotated[
        str | None, typer.Option("--release", help="Verified experience release JSON")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecommendInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        store=store,
        limit=limit,
        release=release,
    )
    execute_command("experience", command_input, handlers.recommend)


@experience_app.command("plan", help="Write a reviewable optimization plan")
def plan_cmd(
    *,
    store: StoreOption,
    output: Annotated[str, typer.Option("--output", help="Optimization plan JSON")],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    release: Annotated[
        str | None, typer.Option("--release", help="Verified experience release JSON")
    ] = None,
    allow_parameters: Annotated[
        list[str] | None,
        typer.Option("--allow-param", help="Authorize a reviewed PNR parameter; repeatable"),
    ] = None,
    max_trials: Annotated[
        int,
        typer.Option(
            "--max-trials",
            min=2,
            max=100,
            help="Workspace budget including the independent winner rerun",
        ),
    ] = 4,
    max_seconds: Annotated[int, typer.Option("--max-seconds", min=1)] = 3600,
    trial_timeout: Annotated[int, typer.Option("--trial-timeout", min=1)] = 900,
    patience: Annotated[int, typer.Option("--patience", min=1)] = 3,
    target_score: Annotated[float | None, typer.Option("--target-score")] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = PlanInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        store=store,
        output_path=output,
        limit=limit,
        release=release,
        optimization={
            "allow_parameters": allow_parameters,
            "max_trials": max_trials,
            "max_seconds": max_seconds,
            "trial_timeout_seconds": trial_timeout,
            "patience": patience,
            "target_score": target_score,
        }
        if allow_parameters
        else None,
    )
    execute_command("experience", command_input, handlers.plan)


@experience_app.command("optimize", help="Execute an explicitly bounded plan in new workspaces")
def optimize_cmd(
    *,
    store: StoreOption,
    plan: Annotated[str, typer.Option("--plan", help="Reviewed optimization plan JSON")],
    output: Annotated[
        str, typer.Option("--output", help="New directory for results and command logs")
    ],
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = OptimizeInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        store=store,
        plan_path=plan,
        output_path=output,
    )
    execute_command("experience", command_input, handlers.optimize)


@experience_app.command("evaluate", help="Compare two verified experience cases")
def evaluate_cmd(
    *,
    store: StoreOption,
    baseline: Annotated[str, typer.Option("--baseline", help="Baseline case ID")],
    candidate: Annotated[str, typer.Option("--candidate", help="Candidate case ID")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = EvaluationInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(None),
        store=store,
        baseline=baseline,
        candidate=candidate,
    )
    execute_command("experience", command_input, handlers.evaluate)


@release_app.command("create", help="Create a release from verified case IDs")
def release_create_cmd(
    *,
    store: StoreOption,
    output: Annotated[str, typer.Option("--output", help="Release JSON")],
    case_ids: Annotated[list[str] | None, typer.Option("--case-id", help="Verified case ID")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReleaseInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(None),
        store=store,
        case_ids=case_ids,
        output_path=output,
    )
    execute_command("experience", command_input, handlers.release_create)


@release_app.command("verify", help="Verify a release against an experience store")
def release_verify_cmd(
    *,
    store: StoreOption,
    release: Annotated[str, typer.Option("--release", help="Release JSON")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReleaseInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(None),
        store=store,
        release_path=release,
    )
    execute_command("experience", command_input, handlers.release_verify)


@campaign_app.command("validate", help="Validate a campaign manifest without running EDA")
def campaign_validate_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
    )
    execute_command("experience", command_input, handlers.validate_campaign)


@campaign_app.command(
    "run", help="Run isolated serial baselines or resume completed campaign progress"
)
def campaign_run_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    retry_failed: Annotated[
        bool,
        typer.Option(
            "--retry-failed", help="Create a new bounded attempt for unsuccessful designs"
        ),
    ] = False,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().absolute()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        retry_failed=retry_failed,
    )
    execute_command("experience", command_input, handlers.run_campaign)


@campaign_app.command("recover", help="Recover a stopped attempt with quiescent command receipts")
def campaign_recover_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    trial_id: Annotated[str, typer.Option("--trial-id", help="Interrupted campaign attempt ID")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().absolute()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        trial_id=trial_id,
    )
    execute_command("experience", command_input, handlers.recover_campaign)


@campaign_app.command("init", help="Initialize a resumable campaign ledger")
def campaign_init_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    ledger: Annotated[
        str | None, typer.Option("--ledger", help="Ledger path below output_root")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        ledger=ledger,
    )
    execute_command("experience", command_input, handlers.init_campaign)


@campaign_app.command("record", help="Record one externally executed campaign trial")
def campaign_record_cmd(
    *,
    ledger: Annotated[str, typer.Option("--ledger", help="Campaign ledger JSON")],
    design_id: Annotated[str, typer.Option("--design", help="Campaign design ID")],
    workspace: Annotated[str, typer.Option("--workspace", help="Trial workspace name")],
    status: Annotated[
        str, typer.Option("--status", help="running, pass, fail, blocked or cancelled")
    ],
    trial_id: Annotated[str | None, typer.Option("--trial-id", help="Stable trial ID")] = None,
    case_id: Annotated[
        str | None, typer.Option("--case-id", help="Collected experience case ID")
    ] = None,
    reason: Annotated[
        str | None, typer.Option("--reason", help="Failure or blocking reason")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    ledger_path = Path(ledger).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(ledger_path.parent)),
        manifest=str(ledger_path),
        ledger=str(ledger_path),
        design_id=design_id,
        workspace=workspace,
        status=status,
        trial_id=trial_id,
        case_id=case_id,
        reason=reason,
    )
    execute_command("experience", command_input, handlers.record_campaign_trial)


@campaign_app.command("status", help="Show resumable campaign progress")
def campaign_status_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    ledger: Annotated[
        str | None, typer.Option("--ledger", help="Ledger path below output_root")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        ledger=ledger,
    )
    execute_command("experience", command_input, handlers.campaign_status)


@campaign_app.command("summary", help="Summarize trial states and linked evidence")
def campaign_summary_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    ledger: Annotated[
        str | None, typer.Option("--ledger", help="Ledger path below output_root")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        ledger=ledger,
    )
    execute_command("experience", command_input, handlers.campaign_summary)


@campaign_app.command("quality", help="Check evidence quality across all campaign trial history")
def campaign_quality_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest", help="Campaign manifest JSON")],
    ledger: Annotated[
        str | None, typer.Option("--ledger", help="Ledger path below output_root")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    manifest_path = Path(manifest).expanduser().resolve()
    command_input = CampaignInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(str(manifest_path.parent)),
        manifest=str(manifest_path),
        ledger=ledger,
    )
    execute_command("experience", command_input, handlers.campaign_quality)
