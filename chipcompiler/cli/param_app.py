from typing import Annotated

import typer

from chipcompiler.cli.command_inputs import (
    ParamDiffInput,
    ParamListInput,
    ParamSetInput,
    ParamShowInput,
    ParamUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.invocation import CommandHandler, CommandInputT, execute_command
from chipcompiler.cli.options import JsonlOption, JsonOption, PlainOption, ProjectOption
from chipcompiler.cli.param_handler import param_diff as param_diff_handler
from chipcompiler.cli.param_handler import param_list as param_list_handler
from chipcompiler.cli.param_handler import param_set as param_set_handler
from chipcompiler.cli.param_handler import param_show as param_show_handler
from chipcompiler.cli.param_handler import param_unset as param_unset_handler

param_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Manage EDA parameters",
)


def _finish_param(
    param_command: str,
    command_input: CommandInputT,
    handler: CommandHandler[CommandInputT],
) -> None:
    execute_command("param", command_input, handler, render_key=f"param:{param_command}")


@param_app.command("list")
def list_cmd(
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ParamListInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
    )
    _finish_param("list", command_input, param_list_handler)


@param_app.command("show")
def show_cmd(
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ParamShowInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
        key=key,
    )
    _finish_param("show", command_input, param_show_handler)


@param_app.command("set")
def set_cmd(
    key: Annotated[str, typer.Argument()],
    value: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ParamSetInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
        key=key,
        value=value,
    )
    _finish_param("set", command_input, param_set_handler)


@param_app.command("unset")
def unset_cmd(
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ParamUnsetInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
        key=key,
    )
    _finish_param("unset", command_input, param_unset_handler)


@param_app.command("diff")
def diff_cmd(
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ParamDiffInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
    )
    _finish_param("diff", command_input, param_diff_handler)
