"""Project-level configuration editing commands."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project_config as handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    ProjectAddInput,
    ProjectSetInput,
    ProjectShowInput,
    ProjectUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption

project_app = create_app(help="Edit project declarations in ecc.toml")


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("project", command_input, handler, render_key=f"project:{subcommand}")


@project_app.command("set", help="Set one project declaration")
def set_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "set",
        ProjectSetInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_set,
    )


@project_app.command("unset", help="Remove one project declaration")
def unset_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "unset",
        ProjectUnsetInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
        ),
        handlers.project_unset,
    )


@project_app.command("add", help="Add RTL sources to design.rtl")
def add_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "add",
        ProjectAddInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_add,
    )


@project_app.command("remove", help="Remove RTL sources from design.rtl")
def remove_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "remove",
        ProjectAddInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_remove,
    )


@project_app.command("show", help="Show declarations stored in ecc.toml")
def show_cmd(
    *,
    key: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "show",
        ProjectShowInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
        ),
        handlers.project_show,
    )
