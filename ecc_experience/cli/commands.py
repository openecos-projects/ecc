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
    RecommendInput,
    RecordingInput,
    StoreInput,
)

StoreOption = Annotated[str, typer.Option("--store", help="External experience store directory")]
CaseArgument = Annotated[str, typer.Argument(help="Experience case ID")]

experience_app = create_app(help="Collect, query and verify design experience evidence")
campaign_app = create_app(help="Validate generic experience campaign manifests")
experience_app.add_typer(campaign_app, name="campaign")


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
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = RecommendInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        store=store,
        limit=limit,
    )
    execute_command("experience", command_input, handlers.recommend)


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
