from typing import Annotated

import typer

from chipcompiler.cli.command_handlers.compare import compare_run
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.compare_inputs import CompareRunInput
from chipcompiler.cli.core.inputs import output_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption

compare_app = create_app(help="Compare saved Engineering Snapshots without running EDA tools")


@compare_app.command("run")
def run_cmd(
    *,
    baseline: Annotated[str, typer.Option("--baseline", help="Baseline Engineering Snapshot JSON")],
    current: Annotated[str, typer.Option("--current", help="Current Engineering Snapshot JSON")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    """Compare committed run facts in two saved Engineering Snapshots."""
    command_input = CompareRunInput(
        baseline=baseline,
        current=current,
        output=output_options(plain=plain, json_output=json_output),
    )
    execute_command("compare", command_input, compare_run, render_key="compare:run")
