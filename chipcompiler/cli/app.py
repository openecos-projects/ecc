from collections.abc import Sequence

import click
import typer

from chipcompiler.cli.param_app import param_app
from chipcompiler.cli.project_app import register_project_commands
from chipcompiler.cli.workspace_app import workspace_app

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="ECC - EDA toolchain for RTL-to-GDS flows",
)
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
