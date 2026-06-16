import json
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager, redirect_stdout, suppress
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
    refresh_workspace_config,
    run_workspace_flow,
    run_workspace_step,
    sync_workspace_config,
)

workspace_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Manage legacy runtime workspaces",
)

_KEEP_JSON_STDIO_REDIRECT = False


@contextmanager
def keep_json_stdio_redirect(enabled: bool):
    global _KEEP_JSON_STDIO_REDIRECT

    previous = _KEEP_JSON_STDIO_REDIRECT
    _KEEP_JSON_STDIO_REDIRECT = enabled
    try:
        yield
    finally:
        _KEEP_JSON_STDIO_REDIRECT = previous


def _finish(result: dict, json_output: bool, output_stream=None) -> None:
    if json_output and output_stream is not None:
        print(json.dumps(result, ensure_ascii=False), file=output_stream)
    else:
        render_workspace_response(result, json_output)
    raise typer.Exit(code=exit_code_for_response(result["response"]))


@contextmanager
def _preserve_cli_stdio():
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = None
    saved_stderr_fd = None

    for stream in (sys.stdout, sys.stderr):
        with suppress(Exception):
            stream.flush()

    try:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
    except OSError:
        if saved_stdout_fd is not None:
            os.close(saved_stdout_fd)
        try:
            yield
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
        return

    try:
        yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with suppress(Exception):
                stream.flush()

        try:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr


@contextmanager
def _json_runtime_stdio():
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = None
    saved_stderr_fd = None
    output_stream = None
    close_output_stream = False

    for stream in (sys.stdout, sys.stderr):
        with suppress(Exception):
            stream.flush()

    try:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        try:
            saved_stdout_file_fd = saved_stdout.fileno()
        except (AttributeError, OSError, ValueError):
            output_stream = saved_stdout
        else:
            if saved_stdout_file_fd == 1:
                output_stream = os.fdopen(
                    os.dup(saved_stdout_fd),
                    "w",
                    encoding=getattr(saved_stdout, "encoding", None) or "utf-8",
                    buffering=1,
                    closefd=True,
                )
                close_output_stream = True
            else:
                output_stream = saved_stdout
        os.dup2(2, 1)
        sys.stdout = sys.stderr
    except OSError:
        for fd in (saved_stdout_fd, saved_stderr_fd):
            if fd is not None:
                os.close(fd)
        if close_output_stream and output_stream is not None:
            output_stream.close()
        with redirect_stdout(sys.stderr):
            yield None
        return

    try:
        yield output_stream
    finally:
        for stream in (sys.stdout, sys.stderr):
            with suppress(Exception):
                stream.flush()

        try:
            if not (close_output_stream and _KEEP_JSON_STDIO_REDIRECT):
                os.dup2(saved_stdout_fd, 1)
                os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            if close_output_stream and output_stream is not None:
                output_stream.close()
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr


def _dispatch_runtime(callback: Callable[[], dict], json_output: bool) -> None:
    if json_output:
        with _json_runtime_stdio() as output_stream:
            result = callback()
            _finish(result, json_output, output_stream=output_stream)
        return

    with _preserve_cli_stdio():
        result = callback()
    _finish(result, json_output)


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
        _dispatch_runtime(lambda: create_workspace_from_request(request), json_output)
        return
    _finish(result, json_output)


@workspace_app.command("load", help="Load and validate a legacy runtime workspace")
def load_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: load_workspace(directory), json_output)


@workspace_app.command("run-flow", help="Run the workspace flow")
def run_flow_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    rerun: Annotated[bool, typer.Option("--rerun")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: run_workspace_flow(directory, rerun), json_output)


@workspace_app.command("run-step", help="Run one workspace step")
def run_step_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    step: Annotated[str, typer.Option("--step")] = "",
    rerun: Annotated[bool, typer.Option("--rerun")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: run_workspace_step(directory, step, rerun), json_output)


@workspace_app.command("refresh-config", help="Refresh workspace config from parameters")
def refresh_config_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: refresh_workspace_config(directory), json_output)


@workspace_app.command("sync-config", help="Sync managed workspace config fields to parameters")
def sync_config_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    config_path: Annotated[str, typer.Option("--config-path")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: sync_workspace_config(directory, config_path), json_output)


@workspace_app.command("get-info", help="Show workspace or step runtime information")
def get_info_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    step: Annotated[str, typer.Option("--step")] = "",
    info_id: Annotated[str, typer.Option("--id")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: get_workspace_info(directory, step, info_id), json_output)


@workspace_app.command("get-home", help="Show workspace home-page data")
def get_home_cmd(
    directory: Annotated[str, typer.Option("--directory")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _dispatch_runtime(lambda: get_workspace_home(directory), json_output)
