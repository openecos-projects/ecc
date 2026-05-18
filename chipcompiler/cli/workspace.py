import json
import os
import sys
from collections.abc import Sequence

RESPONSES = {"success", "failed", "error", "warning"}


def workspace_response(cmd: str, response: str, data: dict | None = None,
                       message: Sequence[str] | None = None) -> dict:
    return {
        "cmd": cmd,
        "response": response,
        "data": data or {},
        "message": list(message or []),
    }


def exit_code_for_response(response: str) -> int:
    return 0 if response in {"success", "warning"} else 1


def render_workspace_response(result: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
        return

    status = result.get("response", "")
    cmd = result.get("cmd", "")
    print(f"{cmd}: {status}")
    for message in result.get("message", []):
        print(message)


def dispatch(args) -> tuple[dict, int]:
    handlers = {
        "create": create,
        "load": load,
        "run-flow": run_flow,
        "run-step": run_step,
        "get-info": get_info,
        "get-home": get_home,
    }
    handler = handlers.get(args.workspace_command)
    if handler is None:
        result = workspace_response("", "error", message=["unknown workspace command"])
    else:
        result = handler(args)
    return result, exit_code_for_response(result["response"])


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


def create(args) -> dict:
    try:
        request_data = _create_request_data(args)
        missing = _missing_fields(request_data, ("directory",))
        if missing:
            return workspace_response(
                "create_workspace",
                "failed",
                message=[f"missing required field: {missing[0]}"],
            )

        input_filelist = request_data.get("filelist", "")
        if not input_filelist:
            rtl_paths = _normalize_rtl_list(request_data.get("rtl_list", []))
            if rtl_paths:
                input_filelist = _write_filelist(request_data["directory"], rtl_paths)

        import chipcompiler.data as data_api

        workspace = data_api.create_workspace(
            directory=request_data.get("directory", ""),
            pdk=request_data.get("pdk", ""),
            parameters=request_data.get("parameters", {}),
            origin_def=request_data.get("origin_def", ""),
            origin_verilog=request_data.get("origin_verilog", ""),
            input_filelist=input_filelist,
            pdk_root=request_data.get("pdk_root", ""),
        )
    except InputError as exc:
        return workspace_response("create_workspace", exc.response, message=[str(exc)])
    except Exception as exc:
        return workspace_response(
            "create_workspace",
            "error",
            message=[f"create workspace failed : {exc}"],
        )

    directory = os.path.abspath(request_data["directory"])
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


def load(args) -> dict:
    cmd = "load_workspace"
    if not args.directory:
        return workspace_response(cmd, "failed", message=["missing required field: directory"])

    try:
        workspace, _engine_flow = load_workspace_runtime(args.directory)
    except WorkspaceValidationError as exc:
        return workspace_response(cmd, "failed", message=[str(exc)])
    except Exception as exc:
        return workspace_response(cmd, "error", message=[f"load workspace failed : {exc}"])

    directory = os.path.abspath(workspace.directory)
    return workspace_response(
        cmd,
        "success",
        data={"directory": directory, "workspace_id": directory},
        message=[f"load workspace success : {directory}"],
    )


def run_flow(args) -> dict:
    cmd = "run_flow"
    response_data = {"rerun": bool(args.rerun)}
    if not args.directory:
        return workspace_response(
            cmd,
            "failed",
            data=response_data,
            message=["missing required field: directory"],
        )

    try:
        workspace, engine_flow = load_workspace_runtime(args.directory)
        if not engine_flow.run_steps(rerun=args.rerun):
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


def run_step(args) -> dict:
    cmd = "run_step"
    step = args.step or ""
    response_data = {"step": step, "state": "Unstart"}
    if not args.directory:
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
        workspace, engine_flow = load_workspace_runtime(args.directory)
        state = engine_flow.run_step(step, args.rerun)
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


def get_info(args) -> dict:
    cmd = "get_info"
    step = args.step or ""
    info_id = args.id or ""
    response_data = {"step": step, "id": info_id, "info": {}}
    missing = _missing_fields(
        {"directory": args.directory, "step": step, "id": info_id},
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
        workspace, engine_flow = load_workspace_runtime(args.directory)
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


def get_home(args) -> dict:
    cmd = "get_home"
    if not args.directory:
        return workspace_response(cmd, "failed", message=["missing required field: directory"])

    try:
        workspace, _engine_flow = load_workspace_runtime(args.directory)
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


def _create_request_data(args) -> dict:
    has_input = args.input_json is not None
    field_flags = [
        args.directory,
        args.pdk,
        args.pdk_root,
        args.origin_def,
        args.origin_verilog,
        args.filelist,
        args.rtl,
        args.param_json,
    ]
    if has_input and any(bool(flag) for flag in field_flags):
        raise InputError("--input-json and field flags are mutually exclusive")

    if has_input:
        data = _read_json_object(args.input_json)
        _resolve_request_rtl_list(data, _input_json_base_dir(args.input_json))
        return data

    parameters = {}
    if args.param_json:
        parameters = _read_json_object(args.param_json)

    return {
        "directory": args.directory or "",
        "pdk": args.pdk or "",
        "pdk_root": args.pdk_root or "",
        "parameters": parameters,
        "origin_def": args.origin_def or "",
        "origin_verilog": args.origin_verilog or "",
        "filelist": args.filelist or "",
        "rtl_list": _resolve_rtl_flags(args.rtl or []),
    }


def _read_json_object(path: str) -> dict:
    try:
        if path == "-":
            raw = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
    except OSError as exc:
        raise InputError(f"unreadable JSON file: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON input: {exc}") from exc

    if not isinstance(data, dict):
        raise InputError("JSON input must be an object")
    return data


def _normalize_rtl_list(rtl_list) -> list[str]:
    if not rtl_list:
        return []
    if isinstance(rtl_list, list):
        items = rtl_list
    elif isinstance(rtl_list, str):
        items = rtl_list.splitlines()
    else:
        items = [rtl_list]

    result = []
    seen = set()
    for item in items:
        path = str(item).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _resolve_rtl_flags(rtl_paths: Sequence[str]) -> list[str]:
    result = []
    for path in rtl_paths:
        expanded = os.path.expandvars(os.path.expanduser(str(path)))
        result.append(os.path.abspath(expanded))
    return result


def _resolve_request_rtl_list(data: dict, base_dir: str) -> None:
    if data.get("filelist"):
        return
    rtl_list = data.get("rtl_list")
    if not rtl_list:
        return
    data["rtl_list"] = [
        path if os.path.isabs(path) else os.path.abspath(os.path.join(base_dir, path))
        for path in _normalize_rtl_list(rtl_list)
    ]


def _input_json_base_dir(path: str) -> str:
    if path == "-":
        return os.getcwd()
    return os.path.dirname(os.path.abspath(os.path.expanduser(path)))


def _write_filelist(directory: str, rtl_paths: list[str]) -> str:
    os.makedirs(directory, exist_ok=True)
    filelist_path = os.path.join(directory, "filelist")
    with open(filelist_path, "w", encoding="utf-8") as f:
        for path in rtl_paths:
            if any(ch.isspace() for ch in path):
                f.write(f'"{path}"\n')
            else:
                f.write(f"{path}\n")
    return filelist_path


def _looks_like_old_workspace(directory: str) -> bool:
    if not os.path.isdir(directory):
        return False
    home = os.path.join(directory, "home")
    return all(
        os.path.isfile(os.path.join(home, filename))
        for filename in ("parameters.json", "flow.json", "home.json")
    )


def _missing_fields(data: dict, fields: Sequence[str]) -> list[str]:
    return [field for field in fields if not str(data.get(field, "")).strip()]


def _state_value(state) -> str:
    return getattr(state, "value", str(state))


class InputError(Exception):
    def __init__(self, message: str, response: str = "error"):
        super().__init__(message)
        self.response = response


class WorkspaceValidationError(Exception):
    pass
