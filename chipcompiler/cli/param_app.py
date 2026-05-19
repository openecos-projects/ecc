from typing import Annotated

import typer

from chipcompiler.cli.invocation import command_args, finish_command

param_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Manage EDA parameters",
)


def _finish_param(
    param_command: str,
    project: str | None,
    json_output: bool,
    jsonl: bool,
    plain: bool,
    **kwargs,
) -> None:
    finish_command(
        command_args(
            "param",
            param_command=param_command,
            project=project,
            json=json_output,
            jsonl=jsonl,
            plain=plain,
            **kwargs,
        ),
    )


@param_app.command("list")
def list_cmd(
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    _finish_param("list", project, json_output, jsonl, plain)


@param_app.command("show")
def show_cmd(
    key: Annotated[str, typer.Argument()],
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    _finish_param("show", project, json_output, jsonl, plain, key=key)


@param_app.command("set")
def set_cmd(
    key: Annotated[str, typer.Argument()],
    value: Annotated[str, typer.Argument()],
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    _finish_param("set", project, json_output, jsonl, plain, key=key, value=value)


@param_app.command("unset")
def unset_cmd(
    key: Annotated[str, typer.Argument()],
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    _finish_param("unset", project, json_output, jsonl, plain, key=key)


@param_app.command("diff")
def diff_cmd(
    project: Annotated[str | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    plain: Annotated[bool, typer.Option("--plain")] = False,
) -> None:
    _finish_param("diff", project, json_output, jsonl, plain)
