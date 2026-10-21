from typing import Annotated

import typer

from chipcompiler.cli.command_handlers.flow import flow_list, flow_show, flow_validate
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    FlowListInput,
    FlowShowInput,
    FlowValidateInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption

flow_app = create_app(help="Inspect available ECC flows")


@flow_app.command("list")
def list_cmd(*, plain: PlainOption = False, json_output: JsonOption = False) -> None:
    """List registered flows and their ordered steps."""
    command_input = FlowListInput(
        output=output_options(plain=plain, json_output=json_output),
    )
    execute_command("flow", command_input, flow_list, render_key="flow:list")


@flow_app.command("show")
def show_cmd(
    flow_id: Annotated[str, typer.Argument(help="Registered flow preset name")],
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    """Show one registered flow and its ordered steps."""
    command_input = FlowShowInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        flow_id=flow_id,
    )
    execute_command("flow", command_input, flow_show, render_key="flow:show")


@flow_app.command("validate")
def validate_cmd(
    *,
    flow_id: Annotated[str | None, typer.Option("--flow", help="Validate one flow preset")] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    """Validate registered flow definitions and step metadata."""
    command_input = FlowValidateInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        flow_id=flow_id,
    )
    execute_command("flow", command_input, flow_validate, render_key="flow:validate")
