import os

from chipcompiler.cli.workspace_request import (
    InputError,
    WorkspaceCreateRequest,
    missing_fields,
    normalize_rtl_list,
    write_filelist,
)
from chipcompiler.cli.workspace_response import workspace_response


def create_workspace_from_request(request: WorkspaceCreateRequest) -> dict:
    try:
        missing = missing_fields({"directory": request.directory}, ("directory",))
        if missing:
            return workspace_response(
                "create_workspace",
                "failed",
                message=[f"missing required field: {missing[0]}"],
            )

        input_filelist = request.filelist
        if not input_filelist:
            rtl_paths = normalize_rtl_list(request.rtl_list)
            if rtl_paths:
                input_filelist = write_filelist(request.directory, rtl_paths)

        import chipcompiler.data as data_api

        workspace = data_api.create_workspace(
            directory=request.directory,
            pdk=request.pdk,
            parameters=request.parameters,
            origin_def=request.origin_def,
            origin_verilog=request.origin_verilog,
            input_filelist=input_filelist,
            pdk_root=request.pdk_root,
        )
    except InputError as exc:
        return workspace_response("create_workspace", exc.response, message=[str(exc)])
    except Exception as exc:
        return workspace_response(
            "create_workspace",
            "error",
            message=[f"create workspace failed : {exc}"],
        )

    directory = os.path.abspath(request.directory)
    if workspace is None:
        return workspace_response(
            "create_workspace",
            "failed",
            message=[f"create workspace failed : {directory}"],
        )

    try:
        build_flow_for_workspace(workspace)
    except Exception as exc:
        return workspace_response(
            "create_workspace",
            "error",
            message=[f"create workspace flow failed : {exc}"],
        )

    return workspace_response(
        "create_workspace",
        "success",
        data={"directory": directory, "workspace_id": directory},
        message=[f"create workspace success : {directory}"],
    )


def load_workspace(directory: str) -> dict:
    cmd = "load_workspace"
    if not directory:
        return workspace_response(cmd, "failed", message=["missing required field: directory"])

    try:
        workspace, _engine_flow = load_workspace_runtime(directory)
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", message=[str(exc)])
    except Exception as exc:
        return workspace_response(cmd, "error", message=[f"load workspace failed : {exc}"])

    resolved_directory = os.path.abspath(workspace.directory)
    return workspace_response(
        cmd,
        "success",
        data={"directory": resolved_directory, "workspace_id": resolved_directory},
        message=[f"load workspace success : {resolved_directory}"],
    )


def run_workspace_flow(directory: str, rerun: bool) -> dict:
    cmd = "run_flow"
    response_data = {"rerun": bool(rerun)}
    if not directory:
        return workspace_response(
            cmd,
            "failed",
            data=response_data,
            message=["missing required field: directory"],
        )

    try:
        workspace, engine_flow = load_workspace_runtime(directory)
        if rerun:
            engine_flow.clear_states()
        ok = engine_flow.run_steps(rerun=rerun)
        if not ok:
            return workspace_response(
                cmd,
                "failed",
                data=response_data,
                message=[f"run flow failed : {os.path.abspath(workspace.directory)}"],
            )
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", data=response_data, message=[str(exc)])
    except Exception as exc:
        return workspace_response(
            cmd,
            "error",
            data=response_data,
            message=[f"run flow failed : {exc}"],
        )

    return workspace_response(
        cmd,
        "success",
        data=response_data,
        message=[f"run flow success : {os.path.abspath(workspace.directory)}"],
    )


def run_workspace_step(directory: str, step: str, rerun: bool) -> dict:
    cmd = "run_step"
    step = step or ""
    response_data = {"step": step, "state": "Unstart"}
    if not directory:
        return workspace_response(
            cmd,
            "failed",
            data=response_data,
            message=["missing required field: directory"],
        )
    if not step:
        return workspace_response(
            cmd,
            "failed",
            data=response_data,
            message=["missing required field: step"],
        )

    try:
        workspace, engine_flow = load_workspace_runtime(directory)
        state = engine_flow.run_step(step, rerun)
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", data=response_data, message=[str(exc)])
    except Exception as exc:
        return workspace_response(
            cmd,
            "error",
            data=response_data,
            message=[f"run step {step} error : {exc}"],
        )

    state_value = _state_value(state)
    response_data["state"] = state_value
    if state_value == "Success":
        return workspace_response(
            cmd,
            "success",
            data=response_data,
            message=[f"run step {step} success : {os.path.abspath(workspace.directory)}"],
        )

    return workspace_response(
        cmd,
        "failed",
        data=response_data,
        message=[
            f"run step {step} failed with state {state_value} : "
            f"{os.path.abspath(workspace.directory)}"
        ],
    )


def get_workspace_info(directory: str, step: str, info_id: str) -> dict:
    cmd = "get_info"
    step = step or ""
    info_id = info_id or ""
    response_data = {"step": step, "id": info_id, "info": {}}
    missing = missing_fields(
        {"directory": directory, "step": step, "id": info_id},
        ("directory", "step", "id"),
    )
    if missing:
        return workspace_response(
            cmd,
            "failed",
            data=response_data,
            message=[f"missing required field: {missing[0]}"],
        )

    try:
        workspace, engine_flow = load_workspace_runtime(directory)
        workspace_step = engine_flow.get_workspace_step(step)
        if workspace_step is None:
            return workspace_response(
                cmd,
                "failed",
                data=response_data,
                message=[f"step not found: {step}"],
            )
        import chipcompiler.tools as tools_api

        info = tools_api.get_step_info(workspace=workspace, step=workspace_step, id=info_id)
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", data=response_data, message=[str(exc)])
    except Exception as exc:
        return workspace_response(
            cmd,
            "error",
            data=response_data,
            message=[f"get information error for step {step} : {exc}"],
        )

    if not info:
        return workspace_response(
            cmd,
            "warning",
            data=response_data,
            message=[f"no information for step {step} : {os.path.abspath(workspace.directory)}"],
        )

    response_data["info"] = info
    return workspace_response(
        cmd,
        "success",
        data=response_data,
        message=[f"get information success : {step} - {info_id}"],
    )


def get_workspace_home(directory: str) -> dict:
    cmd = "get_home"
    if not directory:
        return workspace_response(cmd, "failed", message=["missing required field: directory"])

    try:
        workspace, _engine_flow = load_workspace_runtime(directory)
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", message=[str(exc)])
    except Exception as exc:
        return workspace_response(cmd, "error", message=[f"get home error : {exc}"])

    path = os.path.abspath(workspace.home.path)
    if os.path.exists(path):
        return workspace_response(
            cmd,
            "success",
            data={"path": path},
            message=[f"get home success : {path}"],
        )
    return workspace_response(
        cmd,
        "failed",
        message=[f"get home failed : {path}"],
    )


def load_workspace_runtime(directory: str):
    import chipcompiler.data as data_api

    if not directory:
        raise WorkspaceValidationError("directory is required")
    if not _looks_like_old_workspace(directory):
        raise WorkspaceValidationError(f"invalid workspace directory: {directory}")

    workspace = data_api.load_workspace(directory=directory)
    if workspace is None:
        raise WorkspaceValidationError(f"load workspace failed : {directory}")

    engine_flow = build_flow_for_workspace(workspace)
    return workspace, engine_flow


def build_flow_for_workspace(workspace):
    import chipcompiler.engine as engine_api
    import chipcompiler.rtl2gds as rtl2gds_api

    engine_flow = engine_api.EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        for step, tool, state in rtl2gds_api.build_rtl2gds_flow():
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()
    return engine_flow


def _looks_like_old_workspace(directory: str) -> bool:
    if not os.path.isdir(directory):
        return False
    home = os.path.join(directory, "home")
    return all(
        os.path.isfile(os.path.join(home, filename))
        for filename in ("parameters.json", "home.json")
    )


def _state_value(state) -> str:
    return getattr(state, "value", str(state))


class WorkspaceValidationError(Exception):
    pass
