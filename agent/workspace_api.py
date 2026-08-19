import json
import shutil
from hashlib import sha256
from pathlib import Path

from chipcompiler.data import StateEnum
from chipcompiler.runtime.requests import WorkspaceIdRequest
from chipcompiler.runtime.workspace_api import (
    RuntimeApiError,
    WorkspaceRuntimeApi,
    _init_db_engine_for_workspace_step,
    _state_value,
)
from chipcompiler.utility.path import path_is_within

from .data import (
    FoundationExtractor,
    bind_candidate_input,
    export_candidate_capabilities,
    materialize_candidate_config,
    reapply_candidate_input_binding,
    validate_candidate_step_contract,
)
from .engine import AgentEngineFlow
from .requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
    CandidateRerunRequest,
    WorkspaceExtractFoundationRequest,
)


def build_agent_flow_for_workspace(workspace, *, create_step_workspaces: bool = True):
    import chipcompiler.rtl2gds as rtl2gds_api

    flow = AgentEngineFlow(workspace=workspace)
    if not flow.has_init():
        for step, tool, state in rtl2gds_api.build_rtl2gds_flow():
            flow.add_step(step=step, tool=tool, state=state)
    if create_step_workspaces:
        flow.create_step_workspaces()
    return flow


class FlowAgentRuntimeApi:
    """Optional Flow Agent RPC handlers over one ECC workspace runtime."""

    def __init__(self, ecc_api: WorkspaceRuntimeApi):
        self.ecc_api = ecc_api

    def extract_foundation(self, request: WorkspaceExtractFoundationRequest) -> dict:
        def extract(session):
            workspace_dir = Path(session.workspace.directory).resolve()
            FoundationExtractor(str(workspace_dir), profile="iccd_full_v1").extract(
                include_raw_refs=False,
                materialize_audit_tables=True,
                route_detail_level="full",
            )
            return _foundation_receipt(workspace_dir)

        return self._with_workspace_lock(request.workspace_id, extract)

    def export_candidate_capabilities(self, request: WorkspaceIdRequest) -> dict:
        return self._with_workspace_lock(
            request.workspace_id,
            lambda session: export_candidate_capabilities(session.workspace),
        )

    def bind_candidate_input(self, request: CandidateBindInputRequest) -> dict:
        def bind(session):
            flow = build_agent_flow_for_workspace(session.workspace)
            return bind_candidate_input(
                session.workspace,
                flow,
                request.target_step,
                request.source_step,
                request.candidate_id,
            )

        return self._with_workspace_lock(request.workspace_id, bind)

    def materialize_candidate(self, request: CandidateMaterializeRequest) -> dict:
        return self._with_workspace_lock(
            request.workspace_id,
            lambda session: materialize_candidate_config(
                session.workspace,
                request.target_step,
                request.patch,
                request.candidate_id,
            ),
        )

    def candidate_rerun(self, request: CandidateRerunRequest) -> dict:
        return self._with_workspace_lock(
            request.workspace_id,
            lambda session: self._candidate_rerun(session, request),
        )

    def _candidate_rerun(self, session, request: CandidateRerunRequest) -> dict:
        should_capture = self.ecc_api._should_capture_session_db(session)
        previous_db = session.db_handle if should_capture else None
        if should_capture:
            self.ecc_api._release_session_db(session)
            previous_db = None
        flow = self._build_flow(session)
        try:
            steps = _candidate_rerun_steps(
                flow,
                request.target_step,
                request.end_step,
                request.execution_scope,
            )
            if request.patch:
                _materialize_candidate_rerun(session.workspace, flow, request)
            _prepare_candidate_rerun(session.workspace, flow, steps)
            if request.patch:
                _reapply_candidate_input(session.workspace, flow, request.target_step)
            for step in steps:
                _run_candidate_step(flow, step)
            return {
                "end_step": request.end_step,
                "execution_scope": request.execution_scope,
                "target_step": request.target_step,
            }
        finally:
            self._finish_flow(
                session,
                flow,
                should_capture=should_capture,
                previous_db=previous_db,
            )

    def _build_flow(self, session):
        flow = build_agent_flow_for_workspace(session.workspace)
        return flow

    def _finish_flow(self, session, flow, *, should_capture: bool, previous_db) -> None:
        if should_capture:
            self.ecc_api._capture_flow_db(session, flow, previous_handle=previous_db)
        else:
            self.ecc_api._close_transient_flow_db(flow)

    def _with_workspace_lock(self, workspace_id: str, operation):
        return self.ecc_api._with_session_mutation_lock(workspace_id, operation)


def _foundation_receipt(workspace_dir: Path) -> dict:
    manifest = workspace_dir / "foundation_data/ecc/manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeApiError("command_failed", f"foundation extraction failed: {exc}") from exc
    if payload.get("contract_name") != "foundation_data/ecc":
        raise RuntimeApiError(
            "command_failed", "foundation extractor produced an unsupported contract"
        )
    return {
        "manifestRef": "foundation_data/ecc/manifest.json",
        "manifestSha256": sha256(manifest.read_bytes()).hexdigest(),
        "contractName": payload["contract_name"],
        "schemaVersion": payload.get("schema_version"),
    }


def _candidate_rerun_steps(flow, target_step: str, end_step: str, execution_scope: str) -> list:
    if execution_scope not in {"single_step", "full_flow"}:
        raise RuntimeApiError("invalid_request", "candidate rerun execution scope is invalid")
    steps = list(getattr(flow, "workspace_steps", ()))
    target_index = next(
        (index for index, step in enumerate(steps) if step.name == target_step), None
    )
    end_index = next((index for index, step in enumerate(steps) if step.name == end_step), None)
    if target_index is None or end_index is None:
        raise RuntimeApiError(
            "command_failed", f"rerun step not found: {target_step} or {end_step}"
        )
    if execution_scope == "single_step":
        if target_step != end_step:
            raise RuntimeApiError(
                "invalid_request", "single-step rerun end step must match the target step"
            )
        return [steps[target_index]]
    if end_index < target_index:
        raise RuntimeApiError("invalid_request", "rerun end step precedes the target step")
    return steps[target_index : end_index + 1]


def _materialize_candidate_rerun(workspace, flow, request: CandidateRerunRequest) -> None:
    source_step = _candidate_source_step(flow, request.target_step)
    bind_candidate_input(
        workspace,
        flow,
        request.target_step,
        source_step,
        request.candidate_id,
    )
    materialize_candidate_config(
        workspace,
        request.target_step,
        request.patch,
        request.candidate_id,
    )


def _candidate_source_step(flow, target_step: str) -> str:
    steps = list(getattr(flow, "workspace_steps", ()))
    for index, step in enumerate(steps):
        if step.name == target_step and index:
            return steps[index - 1].name
    raise RuntimeApiError("invalid_request", f"candidate target has no predecessor: {target_step}")


def _reapply_candidate_input(workspace, flow, target_step: str) -> None:
    try:
        candidate_id = validate_candidate_step_contract(workspace, target_step)
        if candidate_id is not None:
            reapply_candidate_input_binding(workspace, flow, target_step)
    except ValueError as error:
        raise RuntimeApiError(
            "command_failed", f"candidate contract is invalid for {target_step}: {error}"
        ) from error


def _prepare_candidate_rerun(workspace, flow, steps: list) -> None:
    workspace_root = Path(workspace.directory).resolve()
    for step in steps:
        for directory in _candidate_step_artifact_dirs(step):
            _clear_candidate_artifact_dir(workspace_root, directory, step.name)
        record = flow.get_step(step.name, step.tool)
        if record is None:
            raise RuntimeApiError("command_failed", f"candidate flow state is missing: {step.name}")
        record.update({"state": "Unstart", "runtime": "", "peak memory (mb)": 0})
    flow.save()


def _candidate_step_artifact_dirs(step) -> tuple[Path, ...]:
    directories = []
    for field in ("output", "data", "feature", "analysis", "report", "log"):
        value = getattr(step, field, {})
        directory = value.get("dir") if isinstance(value, dict) else getattr(value, "dir", None)
        if directory:
            directories.append(Path(directory))
    return tuple(dict.fromkeys(directories))


def _clear_candidate_artifact_dir(workspace_root: Path, directory: Path, step_name: str) -> None:
    resolved = directory.resolve()
    if (
        resolved == workspace_root
        or not path_is_within(resolved, workspace_root)
        or directory.is_symlink()
    ):
        raise RuntimeApiError(
            "command_failed", f"candidate artifact escapes workspace: {step_name}"
        )
    if directory.exists():
        if not directory.is_dir():
            raise RuntimeApiError(
                "command_failed", f"candidate artifact is not a directory: {step_name}"
            )
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def _run_candidate_step(flow, step) -> None:
    from chipcompiler.runtime.log_stream import archive_own_step_logs

    _init_db_engine_for_workspace_step(flow, step)
    # In-process execution is still executor+client in one process: route the
    # own fd-2 stream through the reader so markers are consumed and the
    # step's bytes land in its archive (echoed to the real stderr).
    with archive_own_step_logs(flow.workspace.directory) as reader:
        state = flow.run_step(step, rerun=True)
    # An archive failure or unmatched begin must not report success while the
    # step's log is missing; downgrade so a later rerun rebuilds it.
    if reader.state.error is not None or reader.state.active_step is not None:
        record = flow.get_step(step.name, step.tool)
        if record is not None:
            record["state"] = StateEnum.Imcomplete.value
            flow.save()
        raise RuntimeApiError(
            "command_failed",
            f"candidate rerun step {step.name} log archival failed: "
            f"{reader.state.error or 'unmatched begin marker'}",
        )
    if _state_value(state) != "Success":
        raise RuntimeApiError(
            "command_failed",
            f"candidate rerun step {step.name} failed with state {_state_value(state)}",
        )
