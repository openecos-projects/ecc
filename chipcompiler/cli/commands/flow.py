from typing import Annotated, Any

import typer

from chipcompiler.cli.command_handlers.flow import flow_list, flow_show, flow_validate
from chipcompiler.cli.command_handlers.flow_selection import flow_edit, flow_status
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.completion import complete_flow_step, complete_inserted_step
from chipcompiler.cli.core.inputs import (
    FlowEditInput,
    FlowListInput,
    FlowShowInput,
    FlowStatusInput,
    FlowValidateInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption

flow_app = create_app(help="Inspect available ECC flows and the project's step selection")


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


def _step_toggle(flag: str, help_text: str) -> Any:
    """A repeatable step-name option with shell completion."""
    return typer.Option(flag, help=help_text, autocompletion=complete_flow_step)


def _step_insertion(flag: str, help_text: str) -> Any:
    """A repeatable ``STEP@AFTER`` option with shell completion."""
    return typer.Option(flag, help=help_text, autocompletion=complete_inserted_step)


@flow_app.command("status")
def status_cmd(
    *,
    enable: Annotated[
        list[str] | None, _step_toggle("--enable", "Also run STEP (repeatable)")
    ] = None,
    disable: Annotated[
        list[str] | None, _step_toggle("--disable", "Also skip STEP (repeatable)")
    ] = None,
    insert: Annotated[
        list[str] | None,
        _step_insertion("--insert", "Also insert lec@AFTER, an LEC after AFTER (repeatable)"),
    ] = None,
    remove: Annotated[
        list[str] | None, _step_insertion("--remove", "Also remove inserted lec@AFTER (repeatable)")
    ] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    """Show the project's flow steps and check that the selection can run.

    --enable/--disable/--insert/--remove try a selection without changing
    ecc.toml. Exits 1 when an enabled step lacks design data it requires or an
    entry input is missing.
    """
    command_input = FlowStatusInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        enable=tuple(enable or ()),
        disable=tuple(disable or ()),
        insert=tuple(insert or ()),
        remove=tuple(remove or ()),
    )
    execute_command("flow", command_input, flow_status, render_key="flow:status")


@flow_app.command("edit")
def edit_cmd(
    *,
    enable: Annotated[list[str] | None, _step_toggle("--enable", "Run STEP (repeatable)")] = None,
    disable: Annotated[
        list[str] | None, _step_toggle("--disable", "Skip STEP (repeatable)")
    ] = None,
    insert: Annotated[
        list[str] | None,
        _step_insertion("--insert", "Insert lec@AFTER, an LEC after AFTER (repeatable)"),
    ] = None,
    remove: Annotated[
        list[str] | None, _step_insertion("--remove", "Remove inserted lec@AFTER (repeatable)")
    ] = None,
    max_parallel_steps: Annotated[
        int | None,
        typer.Option(
            "--max-parallel-steps",
            min=1,
            help="Run at most N steps of one stage at once (1: one at a time)",
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Write ecc.toml without asking to confirm")
    ] = False,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    """Choose the project's flow steps and write them to ecc.toml [flow].

    Without --enable/--disable/--insert/--remove/--max-parallel-steps, opens a
    checkbox list in the terminal. The changes are shown for confirmation
    before writing, unless --yes is given (required without a terminal). The
    preset, LEC engine, skip_steps and max_parallel_steps are always written
    explicitly; insert_steps is written when a step is inserted.
    """
    command_input = FlowEditInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        enable=tuple(enable or ()),
        disable=tuple(disable or ()),
        insert=tuple(insert or ()),
        remove=tuple(remove or ()),
        max_parallel_steps=max_parallel_steps,
        yes=yes,
    )
    execute_command("flow", command_input, flow_edit, render_key="flow:edit")
