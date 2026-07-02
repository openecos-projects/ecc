from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from chipcompiler.runtime.requests import (
    FlowRunRequest,
    FlowRunStepRequest,
    WorkspaceCreateRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
)
from chipcompiler.runtime.sessions import (
    WorkspaceSession,
    WorkspaceSessionNotFound,
    WorkspaceSessionRegistry,
)
from chipcompiler.utility.path import path_is_within, stringify_paths

_T = TypeVar("_T")


class RuntimeApiError(RuntimeError):
    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class WorkspaceRuntimeApi:
    def __init__(self, sessions: WorkspaceSessionRegistry | None = None):
        self.sessions = sessions or WorkspaceSessionRegistry()

    def create_workspace(self, request: WorkspaceCreateRequest) -> dict:
        if not request.directory:
            raise RuntimeApiError("invalid_request", "missing required field: directory")

        input_filelist = request.filelist
        if not input_filelist:
            rtl_paths = _normalize_rtl_list(request.rtl_list or [])
            if rtl_paths:
                input_filelist = _write_filelist(request.directory, rtl_paths)

        import chipcompiler.data as data_api

        workspace = data_api.create_workspace(
            directory=request.directory,
            pdk=request.pdk,
            parameters=request.parameters or {},
            origin_def=request.origin_def,
            origin_verilog=request.origin_verilog,
            input_filelist=input_filelist,
            pdk_root=request.pdk_root,
            pdk_json=request.pdk_json,
        )
        if workspace is None:
            raise RuntimeApiError(
                "command_failed",
                f"create workspace failed : {os.path.abspath(request.directory)}",
            )

        build_flow_for_workspace(workspace)
        session = self.sessions.create_session(workspace.directory, workspace=workspace)
        return _workspace_session_result(session)

    def open_workspace(self, request: WorkspaceOpenRequest) -> dict:
        workspace = self._load_workspace(request.directory)
        build_flow_for_workspace(workspace, create_step_workspaces=False)
        session = self.sessions.open_session(workspace.directory, workspace=workspace)
        return _workspace_session_result(session)

    def workspace_home(self, request: WorkspaceIdRequest) -> dict:
        session = self._get_session(request.workspace_id)
        path = Path(session.workspace.home.path).resolve()
        if not path.exists():
            raise RuntimeApiError("command_failed", f"get home failed : {path}")
        return {"path": str(path)}

    def workspace_info(self, request: WorkspaceInfoRequest) -> dict:
        session = self._get_session(request.workspace_id)
        workspace_step = _workspace_step_from_flow(session.workspace, request.step)
        if workspace_step is None:
            raise RuntimeApiError("command_failed", f"step not found: {request.step}")

        import chipcompiler.tools as tools_api

        info = tools_api.get_step_info(
            workspace=session.workspace,
            step=workspace_step,
            id=request.info_id,
        )
        return {
            "step": request.step,
            "id": request.info_id,
            "info": stringify_paths(info or {}),
        }

    def refresh_config(self, request: WorkspaceIdRequest) -> dict:
        def refresh(session: WorkspaceSession) -> dict:
            self._refresh_workspace_config(session.workspace)
            return {"directory": str(session.directory), "refreshed": True}

        return self._with_session_mutation_lock(request.workspace_id, refresh)

    def sync_config(self, request: WorkspaceSyncConfigRequest) -> dict:
        def sync(session: WorkspaceSession) -> dict:
            config_path = Path(request.config_path).resolve()
            config_dir = session.directory / "config"
            if not path_is_within(config_path, config_dir):
                raise RuntimeApiError(
                    "invalid_request",
                    f"config path outside workspace config directory : {config_path}",
                )

            import chipcompiler.data as data_api

            parameters_changed = data_api.sync_workspace_config_to_parameters(
                session.workspace,
                config_path,
            )
            refreshed = False
            if parameters_changed:
                self._refresh_workspace_config(session.workspace)
                refreshed = True
            return {
                "directory": str(session.directory),
                "configPath": str(config_path),
                "parametersChanged": bool(parameters_changed),
                "refreshed": refreshed,
            }

        return self._with_session_mutation_lock(request.workspace_id, sync)

    def reset_flow(self, request: WorkspaceIdRequest) -> dict:
        def reset(session: WorkspaceSession) -> dict:
            engine_flow = build_flow_for_workspace(session.workspace)
            self._prepare_workspace_for_rerun(session.workspace, engine_flow)
            return {"directory": str(session.directory)}

        return self._with_session_mutation_lock(request.workspace_id, reset)

    def close_workspace(self, request: WorkspaceIdRequest) -> dict:
        def close(session: WorkspaceSession) -> dict:
            self.sessions.close_session(session.workspace_id)
            return {"ok": True}

        return self._with_session_mutation_lock(request.workspace_id, close)

    def flow_run(self, request: FlowRunRequest) -> dict:
        def run(session: WorkspaceSession) -> dict:
            engine_flow = build_flow_for_workspace(session.workspace)
            if request.rerun:
                self._prepare_workspace_for_rerun(session.workspace, engine_flow)
            ok = engine_flow.run_steps(rerun=request.rerun)
            if not ok:
                raise RuntimeApiError(
                    "command_failed",
                    f"run flow failed : {session.directory}",
                    {"rerun": request.rerun},
                )
            return {"rerun": request.rerun}

        return self._with_session_mutation_lock(request.workspace_id, run)

    def flow_run_step(self, request: FlowRunStepRequest) -> dict:
        def run_step(session: WorkspaceSession) -> dict:
            engine_flow = build_flow_for_workspace(session.workspace)
            if request.rerun:
                self._refresh_workspace_config(session.workspace)

            workspace_step = engine_flow.get_workspace_step(request.step)
            if workspace_step is None:
                raise RuntimeApiError("command_failed", f"step not found: {request.step}")

            if not request.rerun and engine_flow.check_state(
                name=workspace_step.name,
                tool=workspace_step.tool,
                state=_success_state(),
            ):
                state = engine_flow.run_step(workspace_step, request.rerun)
            else:
                _init_db_engine_for_workspace_step(engine_flow, workspace_step)
                state = engine_flow.run_step(workspace_step, request.rerun)

            state_value = _state_value(state)
            result = {"step": request.step, "state": state_value}
            if state_value != "Success":
                raise RuntimeApiError(
                    "command_failed",
                    f"run step {request.step} failed with state {state_value}",
                    result,
                )
            return result

        return self._with_session_mutation_lock(request.workspace_id, run_step)

    def _load_workspace(self, directory: str):
        if not directory:
            raise RuntimeApiError("invalid_request", "missing required field: directory")
        if not _looks_like_old_workspace(directory):
            raise RuntimeApiError("invalid_request", f"invalid workspace directory: {directory}")

        import chipcompiler.data as data_api

        workspace = data_api.load_workspace(directory=directory)
        if workspace is None:
            raise RuntimeApiError("command_failed", f"load workspace failed : {directory}")
        return workspace

    def _get_session(self, workspace_id: str) -> WorkspaceSession:
        try:
            return self.sessions.get_session(workspace_id)
        except WorkspaceSessionNotFound as exc:
            raise RuntimeApiError(
                "workspace_session_not_found",
                f"workspace session not found: {workspace_id}",
            ) from exc

    def _with_session_mutation_lock(
        self,
        workspace_id: str,
        operation: Callable[[WorkspaceSession], _T],
    ) -> _T:
        session = self._get_session(workspace_id)
        with session.mutation_lock:
            return operation(session)

    def _refresh_workspace_config(self, workspace) -> None:
        import chipcompiler.data as data_api

        data_api.refresh_workspace_config(workspace)

    def _prepare_workspace_for_rerun(self, workspace, engine_flow) -> None:
        import chipcompiler.data as data_api

        data_api.prepare_workspace_for_rerun(workspace, engine_flow)


def build_flow_for_workspace(workspace, create_step_workspaces: bool = True):
    import chipcompiler.engine as engine_api
    import chipcompiler.rtl2gds as rtl2gds_api

    engine_flow = engine_api.EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        for step, tool, state in rtl2gds_api.build_rtl2gds_flow():
            engine_flow.add_step(step=step, tool=tool, state=state)

    if create_step_workspaces:
        engine_flow.create_step_workspaces()
    return engine_flow


def _workspace_session_result(session: WorkspaceSession) -> dict:
    return {"workspaceId": session.workspace_id, "directory": str(session.directory)}


def _normalize_rtl_list(rtl_list: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for item in rtl_list:
        path = str(item).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _write_filelist(directory: str, rtl_paths: list[str]) -> str:
    os.makedirs(directory, exist_ok=True)
    filelist_path = os.path.join(directory, "filelist")
    with open(filelist_path, "w", encoding="utf-8") as f:
        for path in rtl_paths:
            f.write(f'"{path}"\n' if any(ch.isspace() for ch in path) else f"{path}\n")
    return filelist_path


def _looks_like_old_workspace(directory: str) -> bool:
    if not os.path.isdir(directory):
        return False
    home = os.path.join(directory, "home")
    return all(
        os.path.isfile(os.path.join(home, filename))
        for filename in ("parameters.json", "home.json")
    )


def _workspace_step_from_flow(workspace, name: str):
    previous_step = None
    for flow_step in workspace.flow.data.get("steps", []):
        workspace_step = _build_workspace_step_for_info(workspace, flow_step, previous_step)
        if flow_step.get("name") == name:
            return workspace_step
        if workspace_step is not None:
            previous_step = workspace_step
    return None


def _build_workspace_step_for_info(workspace, flow_step: dict, previous_step):
    step_name = flow_step.get("name")
    tool = flow_step.get("tool")
    if not step_name or not tool:
        return None

    if previous_step is None:
        input_def = workspace.design.origin_def
        input_verilog = workspace.design.origin_verilog
        input_db = None
    else:
        input_def = previous_step.output.get("def", "")
        input_verilog = previous_step.output.get("verilog", "")
        input_db = previous_step.output.get("db", "")

    builder = _load_tool_builder(tool)
    if builder is None or not hasattr(builder, "build_step"):
        return None

    return builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
    )


def _load_tool_builder(tool: str):
    import importlib

    module_alias = {
        "klayout": "klayout_tool",
        "dreamplace": "ecc_dreamplace",
        "sizer": "ecc_sizer",
    }
    module_name = module_alias.get(tool, tool)
    return importlib.import_module(f"chipcompiler.tools.{module_name}.builder")


def _init_db_engine_for_workspace_step(engine_flow, workspace_step):
    engine_db = getattr(engine_flow, "engine_db", None)
    if engine_db is None:
        from chipcompiler.engine import EngineDB

        engine_db = EngineDB(workspace=engine_flow.workspace)
        engine_flow.engine_db = engine_db
    elif engine_db.has_init():
        return True

    return engine_db.create_db_engine(step=workspace_step)


def _success_state():
    from chipcompiler.data import StateEnum

    return StateEnum.Success


def _state_value(state: Any) -> str:
    return getattr(state, "value", str(state))
