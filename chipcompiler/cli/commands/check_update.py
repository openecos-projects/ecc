import json
from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import check_update as check_update_handlers
from chipcompiler.cli.core.inputs import CheckUpdateInput, output_options
from chipcompiler.cli.core.invocation import build_context, execute_command
from chipcompiler.cli.core.options import PlainOption


def register_check_update_command(app) -> None:
    app.command("check-update", help="Check whether a newer nightly build is available")(
        check_update_cmd
    )


def check_update_cmd(
    *,
    plain: PlainOption = False,
    # Machine-readable output for the desktop app; not part of the documented CLI surface.
    json_output: Annotated[bool, typer.Option("--json", hidden=True)] = False,
) -> None:
    command_input = CheckUpdateInput(output=output_options(plain=plain))
    if json_output:
        # Same inline machine surface as 'ecc version --json' (see app.py).
        ctx = build_context(command_input)
        result = check_update_handlers.check_update(command_input, ctx)
        typer.echo(json.dumps(result.records[0]))
        return
    execute_command("check-update", command_input, check_update_handlers.check_update)
