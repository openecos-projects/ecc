from chipcompiler.cli.command_handlers.flow import flow_list
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import FlowListInput, output_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption

flow_app = create_app(help="Inspect available ECC flows")


@flow_app.command("list")
def list_cmd(*, plain: PlainOption = False) -> None:
    """List registered flows and their ordered steps."""
    command_input = FlowListInput(
        output=output_options(plain=plain),
    )
    execute_command("flow", command_input, flow_list, render_key="flow:list")
