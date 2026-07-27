from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from copy import copy
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

from chipcompiler.runtime.requests import (
    DbEnsureRequest,
    DbReleaseRequest,
    FlowRunRequest,
    FlowRunStepRequest,
    LayoutEditApplyRequest,
    LayoutEditBeginRequest,
    LayoutEditDiscardRequest,
    LayoutEditSaveRequest,
    WorkspaceCreateRequest,
    WorkspaceExportSignoffRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceInspectSignoffRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
)
from chipcompiler.runtime.sessions import (
    LayoutEditSession,
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
    def __init__(
        self,
        sessions: WorkspaceSessionRegistry | None = None,
        *,
        persistent_db_enabled: bool = False,
    ):
        self.persistent_db_enabled = persistent_db_enabled
        self.sessions = sessions or WorkspaceSessionRegistry(db_releaser=_close_db_handle)
        self._next_layout_edit_id = 1
        self._layout_edit_sessions: dict[str, LayoutEditSession] = {}

    def create_workspace(self, request: WorkspaceCreateRequest) -> dict:
        if not request.directory:
            raise RuntimeApiError("invalid_request", "missing required field: directory")

        temp_filelist_dir = None
        input_filelist = request.filelist
        if not input_filelist:
            rtl_paths = _normalize_rtl_list(request.rtl_list or [])
            if rtl_paths:
                temp_filelist_dir = tempfile.TemporaryDirectory(prefix="ecc-workspace-filelist-")
                input_filelist = _write_filelist(temp_filelist_dir.name, rtl_paths)

        import chipcompiler.data as data_api

        pdk_json, pdk_json_temp_path = _materialize_inline_pdk_json(request.pdk_json)
        try:
            workspace = data_api.create_workspace(
                directory=request.directory,
                pdk=request.pdk,
                parameters=request.parameters or {},
                origin_def=request.origin_def,
                origin_verilog=request.origin_verilog,
                input_filelist=input_filelist,
                pdk_root=request.pdk_root,
                pdk_json=pdk_json,
                sdc=request.sdc,
                flow_config=request.flow_config,
            )
        finally:
            if pdk_json_temp_path is not None:
                pdk_json_temp_path.unlink(missing_ok=True)
            if temp_filelist_dir is not None:
                temp_filelist_dir.cleanup()
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
            self._release_session_db(session)
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
                self._release_session_db(session)
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
            self._release_session_db(session)
            engine_flow = build_flow_for_workspace(session.workspace)
            self._prepare_workspace_for_rerun(session.workspace, engine_flow)
            return {"directory": str(session.directory)}

        return self._with_session_mutation_lock(request.workspace_id, reset)

    def export_signoff(self, request: WorkspaceExportSignoffRequest) -> dict:
        def export(session: WorkspaceSession) -> dict:
            from chipcompiler.runtime.signoff_export import (
                export_signoff_package_archive,
            )

            output_path = export_signoff_package_archive(
                session.workspace,
                request.output_path,
            )
            return {"outputPath": output_path}

        return self._with_session_mutation_lock(request.workspace_id, export)

    def inspect_signoff(self, request: WorkspaceInspectSignoffRequest) -> dict:
        def inspect(session: WorkspaceSession) -> dict:
            from chipcompiler.runtime.signoff_export import inspect_signoff_package

            return inspect_signoff_package(session.workspace)

        return self._with_session_mutation_lock(request.workspace_id, inspect)

    def close_workspace(self, request: WorkspaceIdRequest) -> dict:
        def close(session: WorkspaceSession) -> dict:
            self._discard_layout_edit_session(session)
            self.sessions.close_session(session.workspace_id)
            return {"ok": True}

        return self._with_session_mutation_lock(request.workspace_id, close)

    def flow_run(self, request: FlowRunRequest) -> dict:
        def run(session: WorkspaceSession) -> dict:
            should_capture = self._should_capture_session_db(session)
            previous_db = session.db_handle if should_capture else None
            if request.rerun and should_capture:
                self._release_session_db(session)
                previous_db = None

            engine_flow = self._build_flow_for_session(
                session,
                attach_session_db=should_capture and not request.rerun,
            )
            if request.rerun:
                self._prepare_workspace_for_rerun(session.workspace, engine_flow)
            try:
                ok = engine_flow.run_steps(rerun=request.rerun)
            finally:
                if should_capture:
                    self._capture_flow_db(
                        session,
                        engine_flow,
                        previous_handle=previous_db,
                    )
                else:
                    self._close_transient_flow_db(engine_flow)
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
            should_capture = self._should_capture_session_db(session)
            previous_db = session.db_handle if should_capture else None
            if request.rerun and should_capture:
                self._release_session_db(session)
                previous_db = None

            engine_flow = self._build_flow_for_session(
                session,
                attach_session_db=should_capture and not request.rerun,
            )
            if request.rerun:
                self._refresh_workspace_config(session.workspace)

            workspace_step = engine_flow.get_workspace_step(request.step)
            if workspace_step is None:
                raise RuntimeApiError("command_failed", f"step not found: {request.step}")

            try:
                step_already_succeeded = not request.rerun and engine_flow.check_state(
                    name=workspace_step.name,
                    tool=workspace_step.tool,
                    state=_success_state(),
                )
                if not step_already_succeeded:
                    _init_db_engine_for_workspace_step(engine_flow, workspace_step)
                state = engine_flow.run_step(workspace_step, rerun=request.rerun)
            finally:
                if should_capture:
                    self._capture_flow_db(
                        session,
                        engine_flow,
                        previous_handle=previous_db,
                    )
                else:
                    self._close_transient_flow_db(engine_flow)

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

    def db_ensure(self, request: DbEnsureRequest) -> dict:
        self._require_persistent_db()

        def ensure(session: WorkspaceSession) -> dict:
            db_handle = session.db_handle
            if _db_handle_is_initialized(db_handle):
                return _db_ensure_result(
                    workspace_id=session.workspace_id,
                    step=request.step,
                    active=True,
                    reused=True,
                )

            engine_flow = build_flow_for_workspace(session.workspace)
            if db_handle is not None:
                engine_flow.engine_db = db_handle

            if request.step:
                workspace_step = engine_flow.get_workspace_step(request.step)
                if workspace_step is None:
                    raise RuntimeApiError(
                        "command_failed",
                        f"step not found: {request.step}",
                    )
                initialized = _init_db_engine_for_workspace_step(engine_flow, workspace_step)
            else:
                initialized = engine_flow.init_db_engine()

            flow_db = getattr(engine_flow, "engine_db", None)
            active = bool(initialized and _db_handle_is_initialized(flow_db))
            session.db_handle = flow_db if active else None
            return _db_ensure_result(
                workspace_id=session.workspace_id,
                step=request.step,
                active=active,
                reused=False,
            )

        return self._with_session_mutation_lock(request.workspace_id, ensure)

    def db_release(self, request: DbReleaseRequest) -> dict:
        self._require_persistent_db()

        def release(session: WorkspaceSession) -> dict:
            released = self._release_session_db(session)
            return {"workspaceId": session.workspace_id, "released": released}

        return self._with_session_mutation_lock(request.workspace_id, release)

    def layout_edit_begin(self, request: LayoutEditBeginRequest) -> dict:
        self._require_persistent_db()

        def begin(session: WorkspaceSession) -> dict:
            active_session = session.layout_edit_session
            if active_session is not None:
                if active_session.step_name != request.step:
                    raise RuntimeApiError(
                        "layout_edit_active",
                        f"layout edit session already active for step: {active_session.step_name}",
                        {"editSessionId": active_session.edit_session_id},
                    )
                if (
                    request.expected_source_fingerprint
                    and request.expected_source_fingerprint != active_session.source_fingerprint
                ):
                    raise RuntimeApiError(
                        "source_changed",
                        "layout edit source fingerprint does not match",
                        {
                            "expectedSourceFingerprint": request.expected_source_fingerprint,
                            "actualSourceFingerprint": active_session.source_fingerprint,
                        },
                    )
                return _layout_edit_begin_result(active_session, reused=True)

            engine_flow = build_flow_for_workspace(session.workspace)
            workspace_step = engine_flow.get_workspace_step(request.step)
            if workspace_step is None:
                raise RuntimeApiError("command_failed", f"step not found: {request.step}")

            source_kind, source_paths = _layout_edit_source(workspace_step)
            source_fingerprint = _artifact_fingerprint(source_paths)
            if (
                request.expected_source_fingerprint
                and request.expected_source_fingerprint != source_fingerprint
            ):
                raise RuntimeApiError(
                    "source_changed",
                    "layout edit source fingerprint does not match",
                    {
                        "expectedSourceFingerprint": request.expected_source_fingerprint,
                        "actualSourceFingerprint": source_fingerprint,
                    },
                )

            edit_step = _layout_edit_workspace_step(
                workspace_step,
                source_kind=source_kind,
                source_paths=source_paths,
            )
            initialized = _init_db_engine_for_workspace_step(engine_flow, edit_step)
            db_handle = getattr(engine_flow, "engine_db", None)
            if not initialized or not _db_handle_is_initialized(db_handle):
                _close_db_handle(db_handle)
                raise RuntimeApiError(
                    "command_failed",
                    f"failed to initialize layout edit DB for step: {request.step}",
                )

            module = _db_engine_module(db_handle)
            initialize_geometry = getattr(module, "initialize_geometry_session", None)
            if not callable(initialize_geometry) or not initialize_geometry():
                _close_db_handle(db_handle)
                raise RuntimeApiError(
                    "command_failed",
                    f"failed to initialize layout geometry for step: {request.step}",
                )

            edit_session_id = self._new_layout_edit_id()
            geometry_output_dir = Path(
                tempfile.mkdtemp(prefix=f"ecc-{edit_session_id}-geometry-")
            ) / "geometry-0"
            try:
                _write_layout_edit_geometry_snapshot(module, geometry_output_dir)
            except Exception:
                _close_db_handle(db_handle)
                shutil.rmtree(geometry_output_dir.parent, ignore_errors=True)
                raise

            edit_session = LayoutEditSession(
                edit_session_id=edit_session_id,
                workspace_id=session.workspace_id,
                step_name=request.step,
                workspace_step=workspace_step,
                db_handle=db_handle,
                source_kind=source_kind,
                source_paths=source_paths,
                source_fingerprint=source_fingerprint,
                geometry_output_dir=geometry_output_dir,
            )
            session.layout_edit_session = edit_session
            self._layout_edit_sessions[edit_session.edit_session_id] = edit_session
            return _layout_edit_begin_result(edit_session, reused=False)

        return self._with_session_mutation_lock(request.workspace_id, begin)

    def layout_edit_apply(self, request: LayoutEditApplyRequest) -> dict:
        def apply(session: WorkspaceSession, edit_session: LayoutEditSession) -> dict:
            if not isinstance(request.command_id, str) or not request.command_id.strip():
                raise RuntimeApiError("invalid_request", "missing required field: command_id")

            previous_result = edit_session.command_results.get(request.command_id)
            if previous_result is not None:
                return previous_result

            _validate_layout_edit_revision(request.base_revision, "base_revision")
            if request.base_revision != edit_session.revision:
                raise RuntimeApiError(
                    "version_conflict",
                    "layout edit revision does not match",
                    {
                        "expectedRevision": request.base_revision,
                        "actualRevision": edit_session.revision,
                    },
                )

            placement = _layout_edit_place_instance_operation(request.operation)
            module = _db_engine_module(edit_session.db_handle)
            place_instance = getattr(module, "place_instance", None)
            if not callable(place_instance):
                raise RuntimeApiError("command_failed", "place_instance is unavailable")

            accepted = place_instance(
                inst_name=placement["inst_name"],
                llx=placement["llx"],
                lly=placement["lly"],
                orient=placement["orient"],
                cellmaster=placement["cellmaster"],
                source=placement["source"],
                placement_status=placement["placement_status"],
                create_if_missing=placement["create_if_missing"],
            )
            if not accepted:
                raise RuntimeApiError(
                    "placement_rejected",
                    "place_instance rejected the requested placement",
                    {"instanceName": placement["inst_name"]},
                )

            geometry_delta = _sync_layout_edit_instance_geometry(
                module,
                placement["inst_name"],
            )
            next_geometry_output_dir = (
                edit_session.geometry_output_dir.parent
                / f"geometry-{edit_session.geometry_revision + 1}"
            )
            geometry_manifest_path = _write_layout_edit_geometry_snapshot(
                module,
                next_geometry_output_dir,
            )
            previous_geometry_output_dir = edit_session.geometry_output_dir
            edit_session.geometry_output_dir = next_geometry_output_dir
            shutil.rmtree(previous_geometry_output_dir, ignore_errors=True)
            edit_session.revision += 1
            edit_session.geometry_revision += 1
            edit_session.dirty = True
            result = {
                "editSessionId": edit_session.edit_session_id,
                "commandId": request.command_id,
                "revision": edit_session.revision,
                "geometryRevision": edit_session.geometry_revision,
                "geometryManifestPath": str(geometry_manifest_path),
                "dirty": True,
                "operation": {
                    "kind": "place_instance",
                    "instanceName": placement["inst_name"],
                    "origin": {"x": placement["llx"], "y": placement["lly"]},
                    "orient": placement["orient"],
                },
                "geometryDelta": geometry_delta,
            }
            edit_session.command_results[request.command_id] = result
            return result

        return self._with_layout_edit_session_mutation_lock(request.edit_session_id, apply)

    def layout_edit_save(self, request: LayoutEditSaveRequest) -> dict:
        def save(session: WorkspaceSession, edit_session: LayoutEditSession) -> dict:
            _validate_layout_edit_revision(request.expected_revision, "expected_revision")
            if request.expected_revision != edit_session.revision:
                raise RuntimeApiError(
                    "version_conflict",
                    "layout edit revision does not match",
                    {
                        "expectedRevision": request.expected_revision,
                        "actualRevision": edit_session.revision,
                    },
                )
            if not edit_session.dirty:
                return _layout_edit_save_result(edit_session, saved=False)

            current_fingerprint = _artifact_fingerprint(edit_session.source_paths)
            if current_fingerprint != edit_session.source_fingerprint:
                raise RuntimeApiError(
                    "source_changed",
                    "layout edit source changed after the session began",
                    {
                        "expectedSourceFingerprint": edit_session.source_fingerprint,
                        "actualSourceFingerprint": current_fingerprint,
                    },
                )

            _publish_layout_edit_artifacts(edit_session)
            output_db = _path_or_none(_workspace_step_output_value(edit_session.workspace_step, "db"))
            if output_db is None:
                raise RuntimeApiError("command_failed", "layout edit output DB is missing")
            edit_session.source_kind = "db"
            edit_session.source_paths = (output_db,)
            edit_session.source_fingerprint = _artifact_fingerprint(edit_session.source_paths)
            edit_session.dirty = False
            return _layout_edit_save_result(edit_session, saved=True)

        return self._with_layout_edit_session_mutation_lock(request.edit_session_id, save)

    def layout_edit_discard(self, request: LayoutEditDiscardRequest) -> dict:
        def discard(session: WorkspaceSession, edit_session: LayoutEditSession) -> dict:
            dirty = edit_session.dirty
            self._discard_layout_edit_session(session)
            return {
                "editSessionId": request.edit_session_id,
                "discarded": True,
                "dirty": dirty,
            }

        return self._with_layout_edit_session_mutation_lock(request.edit_session_id, discard)

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

    def _require_persistent_db(self) -> None:
        if not self.persistent_db_enabled:
            raise RuntimeApiError("command_failed", "persistent_db_disabled")

    def _new_layout_edit_id(self) -> str:
        edit_session_id = f"layout-edit-{self._next_layout_edit_id}"
        self._next_layout_edit_id += 1
        return edit_session_id

    def _with_layout_edit_session_mutation_lock(
        self,
        edit_session_id: str,
        operation: Callable[[WorkspaceSession, LayoutEditSession], _T],
    ) -> _T:
        edit_session = self._layout_edit_sessions.get(edit_session_id)
        if edit_session is None:
            raise RuntimeApiError(
                "layout_edit_session_not_found",
                f"layout edit session not found: {edit_session_id}",
            )

        def run(session: WorkspaceSession) -> _T:
            if session.layout_edit_session is not edit_session:
                self._layout_edit_sessions.pop(edit_session_id, None)
                raise RuntimeApiError(
                    "layout_edit_session_not_found",
                    f"layout edit session not found: {edit_session_id}",
                )
            return operation(session, edit_session)

        return self._with_session_mutation_lock(edit_session.workspace_id, run)

    def _discard_layout_edit_session(self, session: WorkspaceSession) -> bool:
        edit_session = session.layout_edit_session
        if edit_session is None:
            return False
        self._layout_edit_sessions.pop(edit_session.edit_session_id, None)
        return self.sessions.release_layout_edit_session(session)

    def _release_session_db(self, session: WorkspaceSession) -> bool:
        return self.sessions.release_session_db(session)

    def _should_capture_session_db(self, session: WorkspaceSession) -> bool:
        return self.persistent_db_enabled and _db_handle_is_initialized(session.db_handle)

    def _build_flow_for_session(
        self,
        session: WorkspaceSession,
        *,
        attach_session_db: bool,
    ):
        engine_flow = build_flow_for_workspace(session.workspace)
        if attach_session_db:
            engine_flow.engine_db = session.db_handle
        return engine_flow

    def _capture_flow_db(
        self,
        session: WorkspaceSession,
        engine_flow,
        *,
        previous_handle,
    ) -> None:
        flow_db = getattr(engine_flow, "engine_db", None)
        if _db_handle_is_initialized(flow_db):
            session.db_handle = flow_db
            if previous_handle is not None and previous_handle is not flow_db:
                _close_db_handle(previous_handle)
            return

        session.db_handle = None
        if previous_handle is not None:
            _close_db_handle(previous_handle)

    def _close_transient_flow_db(self, engine_flow) -> None:
        _close_db_handle(getattr(engine_flow, "engine_db", None))

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


def _layout_edit_begin_result(edit_session: LayoutEditSession, *, reused: bool) -> dict:
    return {
        "editSessionId": edit_session.edit_session_id,
        "workspaceId": edit_session.workspace_id,
        "step": edit_session.step_name,
        "source": edit_session.source_kind,
        "sourceFingerprint": edit_session.source_fingerprint,
        "geometryManifestPath": str(edit_session.geometry_output_dir / "geometry.manifest"),
        "revision": edit_session.revision,
        "geometryRevision": edit_session.geometry_revision,
        "dirty": edit_session.dirty,
        "reused": reused,
    }


def _layout_edit_save_result(edit_session: LayoutEditSession, *, saved: bool) -> dict:
    artifacts = _layout_edit_published_artifacts(edit_session.workspace_step)
    return {
        "editSessionId": edit_session.edit_session_id,
        "revision": edit_session.revision,
        "geometryRevision": edit_session.geometry_revision,
        "dirty": edit_session.dirty,
        "saved": saved,
        "sourceFingerprint": edit_session.source_fingerprint,
        "artifacts": artifacts,
    }


def _layout_edit_published_artifacts(workspace_step) -> dict:
    geometry_dir = _path_or_none(_workspace_step_output_value(workspace_step, "geometry"))
    geometry_manifest = _path_or_none(
        _workspace_step_output_value(workspace_step, "geometry_manifest")
    )
    if geometry_manifest is None and geometry_dir is not None:
        geometry_manifest = geometry_dir / "geometry.manifest"
    return {
        "defPath": _path_text(_workspace_step_output_value(workspace_step, "def")),
        "dbPath": _path_text(_workspace_step_output_value(workspace_step, "db")),
        "gdsPath": _path_text(_workspace_step_output_value(workspace_step, "gds")),
        "geometryManifestPath": str(geometry_manifest) if geometry_manifest else "",
    }


def _layout_edit_source(workspace_step) -> tuple[str, tuple[Path, ...]]:
    output_db = _path_or_none(_workspace_step_output_value(workspace_step, "db"))
    if output_db is not None and output_db.is_dir():
        return "db", (output_db,)

    output_def = _existing_layout_def_path(_workspace_step_output_value(workspace_step, "def"))
    if output_def is not None:
        return "def", (output_def,)

    raise RuntimeApiError(
        "command_failed",
        f"layout edit source missing for step: {getattr(workspace_step, 'name', '')}",
    )


def _layout_edit_workspace_step(
    workspace_step,
    *,
    source_kind: str,
    source_paths: tuple[Path, ...],
):
    edit_input = copy(getattr(workspace_step, "input", {}))
    output_def = _existing_layout_def_path(_workspace_step_output_value(workspace_step, "def"))
    if isinstance(edit_input, dict):
        edit_input["db"] = source_paths[0] if source_kind == "db" else None
        edit_input["def"] = output_def
        edit_step = copy(workspace_step)
        edit_step.input = edit_input
        return edit_step

    edit_input.db = source_paths[0] if source_kind == "db" else None
    edit_input.def_ = output_def
    return replace(workspace_step, input=edit_input)


def _layout_edit_place_instance_operation(operation: object) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise RuntimeApiError("invalid_request", "operation must be an object")
    if operation.get("kind") != "place_instance":
        raise RuntimeApiError("invalid_request", "unsupported layout edit operation")

    inst_name = _layout_edit_text(operation, "inst_name", "instName")
    cellmaster = _layout_edit_optional_text(operation, "cellmaster", "cellMaster")
    source = _layout_edit_optional_text(operation, "source")
    placement_status = _layout_edit_optional_text(
        operation,
        "placement_status",
        "placementStatus",
    ) or "preserve"
    create_if_missing = _layout_edit_optional_bool(
        operation,
        "create_if_missing",
        "createIfMissing",
        default=False,
    )
    orient = _layout_edit_optional_text(operation, "orient")
    if not orient and (placement_status != "preserve" or create_if_missing):
        raise RuntimeApiError("invalid_request", "missing required operation field: orient")
    return {
        "inst_name": inst_name,
        "llx": _layout_edit_integer(operation, "llx"),
        "lly": _layout_edit_integer(operation, "lly"),
        "orient": orient,
        "cellmaster": cellmaster,
        "source": source,
        "placement_status": placement_status,
        "create_if_missing": create_if_missing,
    }


def _layout_edit_text(operation: dict, *keys: str) -> str:
    value = _layout_edit_value(operation, *keys)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeApiError("invalid_request", f"missing required operation field: {keys[0]}")
    return value


def _layout_edit_optional_text(operation: dict, *keys: str) -> str:
    value = _layout_edit_value(operation, *keys, default="")
    if not isinstance(value, str):
        raise RuntimeApiError("invalid_request", f"operation field must be a string: {keys[0]}")
    return value


def _layout_edit_integer(operation: dict, *keys: str) -> int:
    value = _layout_edit_value(operation, *keys)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeApiError("invalid_request", f"operation field must be an integer: {keys[0]}")
    return value


def _layout_edit_optional_bool(
    operation: dict,
    *keys: str,
    default: bool,
) -> bool:
    value = _layout_edit_value(operation, *keys, default=default)
    if not isinstance(value, bool):
        raise RuntimeApiError("invalid_request", f"operation field must be a boolean: {keys[0]}")
    return value


def _layout_edit_value(operation: dict, *keys: str, default: object = None):
    present = [key for key in keys if key in operation]
    if len(present) > 1:
        raise RuntimeApiError("invalid_request", f"duplicate operation field: {keys[0]}")
    return operation[present[0]] if present else default


def _validate_layout_edit_revision(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeApiError("invalid_request", f"{field_name} must be a non-negative integer")


def _sync_layout_edit_instance_geometry(module, inst_name: str) -> dict:
    sync_instance = getattr(module, "sync_instance_geometry", None)
    if not callable(sync_instance):
        return {
            "ok": False,
            "snapshotRequired": True,
            "updatedShapeCount": 0,
            "insertedShapeCount": 0,
            "deletedShapeCount": 0,
            "missingShapeCount": 0,
            "events": [],
        }

    result = sync_instance(inst_name)
    if not isinstance(result, dict):
        return {
            "ok": False,
            "snapshotRequired": True,
            "updatedShapeCount": 0,
            "insertedShapeCount": 0,
            "deletedShapeCount": 0,
            "missingShapeCount": 0,
            "events": [],
        }
    return {
        "ok": bool(result.get("ok", False)),
        "snapshotRequired": bool(result.get("snapshotRequired", False)),
        "updatedShapeCount": _geometry_delta_count(result, "updatedShapeCount"),
        "insertedShapeCount": _geometry_delta_count(result, "insertedShapeCount"),
        "deletedShapeCount": _geometry_delta_count(result, "deletedShapeCount"),
        "missingShapeCount": _geometry_delta_count(result, "missingShapeCount"),
        "events": result.get("events", []) if isinstance(result.get("events", []), list) else [],
    }


def _write_layout_edit_geometry_snapshot(module, output_dir: Path) -> Path:
    save_snapshot = getattr(module, "geometry_session_snapshot_save", None)
    if not callable(save_snapshot):
        save_snapshot = getattr(module, "geometry_snapshot_save", None)
    if not callable(save_snapshot) or not save_snapshot(output_dir=str(output_dir)):
        raise RuntimeApiError("command_failed", "failed to write layout edit geometry snapshot")
    manifest = output_dir / "geometry.manifest"
    if not manifest.is_file():
        raise RuntimeApiError("command_failed", "layout edit geometry manifest is missing")
    return manifest


def _geometry_delta_count(delta: dict, key: str) -> int:
    value = delta.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _publish_layout_edit_artifacts(edit_session: LayoutEditSession) -> None:
    targets = _layout_edit_publish_targets(edit_session.workspace_step)
    stage_parent = _layout_edit_stage_parent(targets.values())
    stage_root = Path(
        tempfile.mkdtemp(prefix=f".layout-edit-{edit_session.edit_session_id}-", dir=stage_parent)
    )
    staged = {
        "def": stage_root / targets["def"].name,
        "db": stage_root / targets["db"].name,
        "gds": stage_root / targets["gds"].name,
        "geometry": stage_root / targets["geometry"].name,
    }
    try:
        module = _db_engine_module(edit_session.db_handle)
        module.def_save(def_path=str(staged["def"]))
        module.save_data(path=str(staged["db"]))
        module.gds_save(output_path=str(staged["gds"]))
        if not module.geometry_snapshot_save(output_dir=str(staged["geometry"])):
            raise RuntimeApiError("command_failed", "failed to export layout geometry snapshot")
        _validate_layout_edit_staging(staged, targets)
        _publish_staged_layout_edit_artifacts(stage_root, staged, targets)
    except RuntimeApiError:
        raise
    except Exception as exc:
        raise RuntimeApiError("command_failed", f"failed to publish layout edit: {exc}") from exc
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _layout_edit_publish_targets(workspace_step) -> dict[str, Path]:
    targets = {
        key: _path_or_none(_workspace_step_output_value(workspace_step, key))
        for key in ("def", "db", "gds", "geometry")
    }
    missing = [key for key, path in targets.items() if path is None]
    if missing:
        raise RuntimeApiError(
            "command_failed",
            f"layout edit output paths missing: {', '.join(missing)}",
        )
    return targets


def _layout_edit_stage_parent(paths) -> Path:
    parents = [str(path.parent) for path in paths]
    common_parent = Path(os.path.commonpath(parents))
    common_parent.mkdir(parents=True, exist_ok=True)
    return common_parent


def _validate_layout_edit_staging(staged: dict[str, Path], targets: dict[str, Path]) -> None:
    manifest = _geometry_manifest_path(staged["geometry"], targets["geometry"], targets)
    missing = []
    if not staged["def"].is_file():
        missing.append("def")
    if not staged["gds"].is_file():
        missing.append("gds")
    if not staged["db"].is_dir() or not any(staged["db"].iterdir()):
        missing.append("db")
    if not manifest.is_file():
        missing.append("geometry_manifest")
    if missing:
        raise RuntimeApiError(
            "command_failed",
            f"layout edit staging validation failed: {', '.join(missing)}",
        )


def _geometry_manifest_path(
    geometry_dir: Path,
    target_geometry_dir: Path,
    targets: dict[str, Path],
) -> Path:
    target_manifest = targets.get("geometry_manifest")
    if target_manifest is None:
        return geometry_dir / "geometry.manifest"
    try:
        return geometry_dir / target_manifest.relative_to(target_geometry_dir)
    except ValueError:
        return geometry_dir / "geometry.manifest"


def _publish_staged_layout_edit_artifacts(
    stage_root: Path,
    staged: dict[str, Path],
    targets: dict[str, Path],
) -> None:
    artifact_keys = ("def", "db", "gds", "geometry")
    backup_dir = stage_root / "backup"
    backup_dir.mkdir()
    journal_path = stage_root / "publish.journal"
    journal_path.write_text(
        json.dumps({"state": "prepared", "artifacts": artifact_keys}),
        encoding="utf-8",
    )
    backups: list[str] = []
    published: list[str] = []
    try:
        for key in artifact_keys:
            target = targets[key]
            if target.exists() or target.is_symlink():
                os.replace(target, backup_dir / key)
                backups.append(key)
        journal_path.write_text(
            json.dumps({"state": "backed_up", "artifacts": backups}),
            encoding="utf-8",
        )
        for key in artifact_keys:
            target = targets[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged[key], target)
            published.append(key)
        journal_path.write_text(
            json.dumps({"state": "published", "artifacts": published}),
            encoding="utf-8",
        )
    except Exception:
        for key in reversed(published):
            _remove_layout_edit_path(targets[key])
        for key in reversed(backups):
            os.replace(backup_dir / key, targets[key])
        raise


def _remove_layout_edit_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _db_engine_module(db_handle):
    module = getattr(db_handle, "engine", None)
    if module is None:
        module = getattr(db_handle, "ecc_module", None)
    if module is None:
        raise RuntimeApiError("command_failed", "layout edit DB module is unavailable")
    return module


def _path_or_none(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(value)


def _workspace_step_output_value(workspace_step, key: str):
    output = getattr(workspace_step, "output", {})
    if isinstance(output, dict):
        return output.get(key)
    return getattr(output, "def_" if key == "def" else key, None)


def _path_text(value: object) -> str:
    path = _path_or_none(value)
    return str(path) if path is not None else ""


def _existing_layout_def_path(value: object) -> Path | None:
    path = _path_or_none(value)
    if path is None:
        return None
    candidates = (path, Path(f"{path}.gz"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _artifact_fingerprint(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        resolved_path = path.resolve()
        digest.update(str(resolved_path).encode("utf-8"))
        if resolved_path.is_dir():
            for item in sorted(resolved_path.rglob("*")):
                if not item.is_file():
                    continue
                stat = item.stat()
                digest.update(str(item.relative_to(resolved_path)).encode("utf-8"))
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        elif resolved_path.is_file():
            stat = resolved_path.stat()
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        else:
            digest.update(b"missing")
    return digest.hexdigest()


def build_flow_for_workspace(workspace, *, create_step_workspaces: bool = True):
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


def _db_ensure_result(
    *,
    workspace_id: str,
    step: str,
    active: bool,
    reused: bool,
) -> dict:
    return {
        "workspaceId": workspace_id,
        "enabled": True,
        "active": active,
        "reused": reused,
        "step": step,
    }


def _db_handle_is_initialized(db_handle) -> bool:
    return db_handle is not None and db_handle.has_init()


def _close_db_handle(db_handle) -> None:
    close = getattr(db_handle, "close", None)
    if callable(close):
        close()


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


def _materialize_inline_pdk_json(pdk_json: Any) -> tuple[Any, Path | None]:
    if not isinstance(pdk_json, dict):
        return pdk_json, None

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="ecc-pdk-",
        suffix=".json",
        delete=False,
    ) as f:
        json.dump(pdk_json, f)
        return f.name, Path(f.name)


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
        input_def = previous_step.output.def_ or ""
        input_verilog = previous_step.output.verilog or ""
        input_db = previous_step.output.db or ""

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
