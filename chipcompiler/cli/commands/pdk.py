from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import pdk as pdk_handlers
from chipcompiler.cli.core.inputs import (
    PdkSetRootInput,
    PdkSetupInput,
    PdkShowInput,
    PdkUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonlOption,
    JsonOption,
    PlainOption,
    ProjectOption,
)

pdk_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Show and configure the PDK path used by this project",
)


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("pdk", command_input, handler, render_key=f"pdk:{subcommand}")


@pdk_app.command("setup", help="Clone + make unzip a PDK checkout, then set it as root")
def setup_cmd(
    *,
    path: Annotated[
        str | None,
        typer.Argument(
            help="PDK checkout path (default: ~/.local/icsprout55-pdk); cloned when missing",
        ),
    ] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = PdkSetupInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        path=path,
    )
    _finish("setup", command_input, pdk_handlers.setup)


@pdk_app.command("set-root", help="Set the [pdk] root path in ecc.toml")
def set_root_cmd(
    *,
    path: Annotated[
        str,
        typer.Argument(help="Path to an icsprout55-pdk checkout (absolute after expansion)"),
    ],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = PdkSetRootInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        path=path,
    )
    _finish("set-root", command_input, pdk_handlers.set_root)


@pdk_app.command("show", help="Show the resolved PDK root and its source")
def show_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = PdkShowInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
    )
    _finish("show", command_input, pdk_handlers.show)


@pdk_app.command("unset", help="Clear [pdk] root (fall back to env vars / repo default)")
def unset_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = PdkUnsetInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
    )
    _finish("unset", command_input, pdk_handlers.unset)
