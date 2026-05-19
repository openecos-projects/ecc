from typing import Annotated

import typer

from chipcompiler.cli.invocation import command_args, finish_command


def register_project_commands(app: typer.Typer) -> None:
    app.command("init")(init_cmd)
    app.command("check")(check_cmd)
    app.command("run")(run_cmd)
    app.command("status")(status_cmd)
    app.command("log")(log_cmd)
    app.command("metrics")(metrics_cmd)
    app.command("artifacts")(artifacts_cmd)
    app.command("config")(config_cmd)
    app.command("diagnose")(diagnose_cmd)


def init_cmd(
    name: Annotated[str, typer.Argument()],
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    finish_command(command_args("init", name=name, plain=plain))


def check_cmd(
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    finish_command(
        command_args("check", project=project, json=json_output, jsonl=False, plain=plain),
    )


def run_cmd(
    project: Annotated[str | None, typer.Option("--project")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    param_set: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help="Set parameter override (repeatable, e.g. --set place.target_density=0.65)",
        ),
    ] = None,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    finish_command(
        command_args(
            "run",
            project=project,
            overwrite=overwrite,
            json=json_output,
            jsonl=jsonl,
            param_set=param_set or [],
            plain=plain,
        ),
    )


def status_cmd(
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    finish_command(
        command_args(
            "status",
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            run_id=run_id,
        ),
    )


def log_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    errors: Annotated[bool, typer.Option("--errors", hidden=True)] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    finish_command(
        command_args(
            "log",
            step=step,
            project=project,
            errors=errors,
            json=json_output,
            plain=plain,
            jsonl=jsonl,
            run_id=run_id,
        ),
    )


def metrics_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    finish_command(
        command_args(
            "metrics",
            step=step,
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            run_id=run_id,
        ),
    )


def artifacts_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    finish_command(
        command_args(
            "artifacts",
            step=step,
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            run_id=run_id,
        ),
    )


def config_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    resolved: Annotated[bool, typer.Option("--resolved")] = False,
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    if not resolved:
        raise typer.BadParameter("--resolved is required", param_hint="--resolved")
    finish_command(
        command_args(
            "config",
            step=step,
            resolved=resolved,
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            run_id=run_id,
        ),
    )


def diagnose_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    finish_command(
        command_args(
            "diagnose",
            step=step,
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            run_id=run_id,
        ),
    )
