import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from typing import Annotated

import typer

from chipcompiler.cli.workspace.request import InputError, create_request
from chipcompiler.cli.workspace.response import (
    exit_code_for_response,
    render_workspace_response,
    workspace_response,
)
from chipcompiler.cli.workspace.service import (
    create_workspace_from_request,
    get_workspace_home,
    get_workspace_info,
    load_workspace,
    run_workspace_flow,
    run_workspace_step,
)

workspace_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Manage legacy runtime workspaces",
)


def _finish(result: dict, json_output: bool) -> None:
    render_workspace_response(result, json_output)
    raise typer.Exit(code=exit_code_for_response(result["response"]))


def _call_runtime(callback: Callable[[], dict], json_output: bool) -> dict:
    if not json_output:
        return callback()
    with redirect_stdout(sys.stderr):
        return callback()


@workspace_app.command("create", help="Create a legacy runtime workspace")
def create_cmd(
    input_json: Annotated[str | None, typer.Option("--input-json")] = None,
    directory: Annotated[str | None, typer.Option("--directory")] = None,
    pdk: Annotated[str | None, typer.Option("--pdk")] = None,
    pdk_root: Annotated[str | None, typer.Option("--pdk-root")] = None,
    origin_def: Annotated[str | None, typer.Option("--origin-def")] = None,
    origin_verilog: Annotated[str | None, typer.Option("--origin-verilog")] = None,
    filelist: Annotated[str | None, typer.Option("--filelist")] = None,
    rtl: Annotated[list[str] | None, typer.Option("--rtl")] = None,
    param_json: Annotated[str | None, typer.Option("--param-json")] = None,
    design: Annotated[str | None, typer.Option("--design")] = None,
    top: Annotated[str | None, typer.Option("--top")] = None,
    clock: Annotated[str | None, typer.Option("--clock")] = None,
    freq: Annotated[float | None, typer.Option("--freq")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        request = create_request(
            input_json=input_json,
            directory=directory,
            pdk=pdk,
            pdk_root=pdk_root,
            origin_def=origin_def,
            origin_verilog=origin_verilog,
            filelist=filelist,
            rtl=rtl or [],
            param_json=param_json,
            design=design,
            top=top,
            clock=clock,
            freq=freq,
        )
    except InputError as exc:
        result = workspace_response("create_workspace", exc.response, message=[str(exc)])
    else:
        result = _call_runtime(lambda: create_workspace_from_request(request), json_output)
    _finish(result, json_output)


@workspace_app.command("load", help="Load and validate a legacy runtime workspace")
def load_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _finish(_call_runtime(lambda: load_workspace(directory), json_output), json_output)


@workspace_app.command("run-flow", help="Run the workspace flow")
def run_flow_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    rerun: Annotated[bool, typer.Option("--rerun")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _finish(_call_runtime(lambda: run_workspace_flow(directory, rerun), json_output), json_output)


@workspace_app.command("run-step", help="Run one workspace step")
def run_step_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    step: Annotated[str, typer.Option("--step")] = "",
    rerun: Annotated[bool, typer.Option("--rerun")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = _call_runtime(lambda: run_workspace_step(directory, step, rerun), json_output)
    _finish(result, json_output)


@workspace_app.command("get-info", help="Show workspace or step runtime information")
def get_info_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    step: Annotated[str, typer.Option("--step")] = "",
    info_id: Annotated[str, typer.Option("--id")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = _call_runtime(lambda: get_workspace_info(directory, step, info_id), json_output)
    _finish(result, json_output)


@workspace_app.command("get-home", help="Show workspace home-page data")
def get_home_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _finish(_call_runtime(lambda: get_workspace_home(directory), json_output), json_output)
