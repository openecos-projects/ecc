import json
from collections.abc import Sequence
from typing import Annotated

import click
import typer

from chipcompiler.cli.commands.param import param_app
from chipcompiler.cli.commands.project import register_project_commands
from chipcompiler.cli.commands.workspace import workspace_app
from chipcompiler.cli.core.version_info import root_version_line, version_payload, version_text

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="ECC - EDA toolchain for RTL-to-GDS flows",
)


def version_callback(value: bool) -> None:
    if value:
        click.echo(root_version_line())
        raise typer.Exit()


@app.callback()
def root_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show ECC version and exit.",
        ),
    ] = None,
) -> None:
    pass


@app.command("version", help="Show ECC runtime and component versions")
def version_cmd(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = version_payload()
    if json_output:
        click.echo(json.dumps(payload))
    else:
        click.echo(version_text(payload))


register_project_commands(app)
app.add_typer(param_app, name="param")
app.add_typer(workspace_app, name="workspace")


def invoke_typer_app(argv: Sequence[str]) -> int:
    if not argv:
        command = typer.main.get_command(app)
        click.echo(command.get_help(click.Context(command, info_name="ecc")), err=True)
        return 1

    command = typer.main.get_command(app)
    try:
        result = command.main(
            args=list(argv),
            prog_name="ecc",
            standalone_mode=False,
        )
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code or 1)
    return int(result or 0)
