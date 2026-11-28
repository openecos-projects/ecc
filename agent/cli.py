"""Adapt a single manifest-managed Workspace to the candidate executor."""

import json
import re
import shutil
import signal
import threading
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, fields
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

import chipcompiler
from chipcompiler.data import load_workspace
from chipcompiler.engine.snapshot.store import read_engineering_snapshot_from_directory
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.runtime_processes import identity_is_live, validate_runtime_entry
from chipcompiler.utility.file import write_text_atomic
from chipcompiler.utility.workspace_lock import workspace_lock

from .candidate_resume import validate_candidate_resume_request
from .data.candidate_artifacts import candidate_lock, validate_candidate_id
from .delivery import retain_candidate
from .operations import RuntimeOperationIdempotencyConflict, RuntimeOperationManager
from .requests import CandidateRerunRequest, CandidateResumeRequest, WorkspaceIdRequest
from .runtime_support import AgentApplicationError
from .workspace_api import (
    FlowAgentRuntimeApi,
    candidate_operation_workspace_id,
    validate_candidate_rerun_request,
)

_RequestT = TypeVar("_RequestT", CandidateRerunRequest, CandidateResumeRequest)


@dataclass
class ManagedSession:
    workspace_revision: int
    workspace: Any = None


class ManagedWorkspace:
    def __init__(
        self,
        project: Path,
        workspace: str,
        operations: RuntimeOperationManager | None = None,
    ):
        self.project = project.resolve()
        self.workspace_id = workspace
        manifest = load_manifest(str(self.project))
        self.project_id = manifest.project_id
        entry = manifest.find_workspace(self.workspace_id)
        if entry is None:
            raise AgentApplicationError("workspace_not_declared", "Source Workspace is unavailable")
        path = Path(entry.workspace_path)
        if not path.is_dir():
            raise AgentApplicationError("workspace_unavailable", "Source Workspace is unavailable")
        self.directory = path.resolve()
        self.operations = operations
        self.expected_revision: int | None = None

    def _get_session(self, workspace_id: str) -> ManagedSession:
        if workspace_id != self.workspace_id:
            raise AgentApplicationError("workspace_unavailable", "Source Workspace is unavailable")
        return ManagedSession(
            workspace_revision=read_engineering_snapshot_from_directory(self.directory)[
                "workspaceRevision"
            ]
        )

    @staticmethod
    def _validate_workspace_revision(session: ManagedSession, expected: int | None) -> None:
        if expected is not None and session.workspace_revision != expected:
            raise AgentApplicationError("revision_conflict", "Workspace Revision does not match")

    @staticmethod
    def _load_workspace(directory: str):
        workspace = load_workspace(directory)
        if workspace is None:
            raise AgentApplicationError(
                "workspace_unavailable", "Candidate Workspace is unavailable"
            )
        return workspace

    @staticmethod
    def _close_transient_flow_db(_flow) -> None:
        # Native databases belong to the candidate step worker process.
        pass

    def _with_session_mutation_lock(self, workspace_id: str, operation):
        with workspace_lock(self.directory, blocking=False):
            session = self._get_session(workspace_id)
            self._validate_workspace_revision(session, self.expected_revision)
            self.require_source_idle()
            session.workspace = load_workspace(self.directory, read_only=True)
            if session.workspace is None:
                raise AgentApplicationError(
                    "workspace_unavailable", "Source Workspace is unavailable"
                )
            return operation(session)

    def require_source_idle(self) -> None:
        processes = load_manifest(str(self.project)).raw.get("runtime_processes", {})
        if self.workspace_id in processes and identity_is_live(
            validate_runtime_entry(processes[self.workspace_id])
        ):
            raise AgentApplicationError(
                "workspace_busy", "Source Workspace already has an active operation"
            )


def _record(record: str, **fields) -> None:
    print(json.dumps({"record": record, **fields}, allow_nan=False), flush=True)


def _parse_request(
    request_type: type[_RequestT], workspace_id: str, payload: dict[str, Any]
) -> _RequestT:
    allowed = {field.name for field in fields(request_type)} - {"workspace_id"}
    required = {
        field.name
        for field in fields(request_type)
        if field.name != "workspace_id" and field.default is field.default_factory
    }
    unknown = payload.keys() - allowed
    missing = required - payload.keys()
    if unknown:
        raise AgentApplicationError(
            "invalid_request",
            f"Unknown candidate request fields: {', '.join(sorted(unknown))}",
        )
    if missing:
        raise AgentApplicationError(
            "invalid_request",
            f"Missing candidate request fields: {', '.join(sorted(missing))}",
        )
    return request_type(workspace_id=workspace_id, **payload)


def run_capabilities(project: Path, workspace_id: str) -> None:
    source = ManagedWorkspace(project, workspace_id)
    api = FlowAgentRuntimeApi(source)
    try:
        capabilities = api.candidate_capabilities(WorkspaceIdRequest(workspace_id))
    except BlockingIOError as exc:
        raise AgentApplicationError(
            "workspace_busy", "Workspace already has an active operation"
        ) from exc
    _record("candidate_capabilities", eccVersion=chipcompiler.__version__, **capabilities)


def run_status(project: Path, workspace_id: str, candidate_id: str) -> None:
    source = ManagedWorkspace(project, workspace_id)
    candidate = validate_candidate_id(candidate_id)
    directory = source.directory / ".agent" / "operations"
    _record("candidate_status", **_candidate_snapshot(source, directory, candidate))


def run_cleanup(project: Path, workspace_id: str, prefix: str) -> None:
    source = ManagedWorkspace(project, workspace_id)
    try:
        removed = cleanup_candidates(source.directory, prefix)
    except BlockingIOError as exc:
        raise AgentApplicationError(
            "workspace_busy", "Workspace already has an active operation"
        ) from exc
    _record("candidate_cleanup", removed=removed)


def run_retain(
    project: Path,
    workspace_id: str,
    *,
    candidate_id: str,
    digest: str,
    target_id: str,
) -> None:
    source = ManagedWorkspace(project, workspace_id)
    try:
        retained = retain_candidate(
            project=source.project,
            project_id=source.project_id,
            source=source.directory,
            workspace_id=source.workspace_id,
            candidate_id=candidate_id,
            digest=digest,
            target_id=target_id,
        )
    except BlockingIOError as exc:
        raise AgentApplicationError(
            "workspace_busy", "Workspace already has an active operation"
        ) from exc
    _record("candidate_retained", **retained)


def run_operation(project: Path, workspace_id: str, operation_id: str, *, cancel: bool) -> None:
    source = ManagedWorkspace(project, workspace_id)
    if re.fullmatch(r"operation-[0-9a-f]{32}", operation_id) is None:
        raise ValueError("Invalid candidate operation ID")
    directory = source.directory / ".agent" / "operations"
    for ledger in sorted(directory.glob("*.json")):
        candidate = validate_candidate_id(ledger.stem)
        snapshot = _candidate_snapshot(source, directory, candidate)
        operation = next(
            (entry for entry in snapshot["operations"] if entry["operationId"] == operation_id),
            None,
        )
        if operation is None:
            continue
        accepted = cancel and operation["state"] in ("queued", "running")
        if accepted:
            write_text_atomic(directory / f"{operation_id}.cancel", "")
        _record("candidate_operation", operation=operation, accepted=accepted)
        return
    raise AgentApplicationError("candidate_unavailable", "Candidate operation is unavailable")


def run_rerun(project: Path, workspace_id: str, payload: dict[str, Any]) -> None:
    request = _parse_request(CandidateRerunRequest, workspace_id, payload)
    validate_candidate_rerun_request(request)
    _run_candidate_operation(
        project,
        workspace_id,
        candidate_id=request.candidate_id,
        expected_revision=request.expected_workspace_revision,
        parent_ref=request.parent_candidate_root_ref,
        starter=lambda api: partial(api.candidate_rerun, request),
    )


def run_resume(project: Path, workspace_id: str, payload: dict[str, Any]) -> None:
    request = _parse_request(CandidateResumeRequest, workspace_id, payload)
    validate_candidate_resume_request(request)
    _run_candidate_operation(
        project,
        workspace_id,
        candidate_id=request.candidate_id,
        expected_revision=request.expected_workspace_revision,
        parent_ref=None,
        starter=lambda api: partial(api.candidate_resume, request),
    )


def _run_candidate_operation(
    project: Path,
    workspace_id: str,
    *,
    candidate_id: str,
    expected_revision: int | None,
    parent_ref: str | None,
    starter: Callable[[FlowAgentRuntimeApi], Callable[[], dict]],
) -> None:
    terminal = threading.Event()
    operations = RuntimeOperationManager(
        lambda event: terminal.set()
        if event.get("type") in {"operation.completed", "operation.cancelled", "operation.failed"}
        else None
    )
    source = ManagedWorkspace(project, workspace_id, operations)
    api = FlowAgentRuntimeApi(source)
    try:
        source.expected_revision = expected_revision
        if source.expected_revision is None:
            raise AgentApplicationError("invalid_request", "Workspace Revision is required")
        directory = source.directory / ".agent" / "operations"
        candidates = {candidate_id}
        if parent_ref is not None:
            parent = Path(parent_ref).name
            if parent == candidate_id:
                raise AgentApplicationError("invalid_request", "Candidate cannot be its own parent")
            candidates.add(parent)
        with ExitStack() as locks:
            for name in sorted(candidates):
                locks.enter_context(candidate_lock(directory, name))
            ledger = directory / f"{candidate_id}.json"
            operation_workspace = candidate_operation_workspace_id(workspace_id, candidate_id)
            operations.load_workspace_ledger(operation_workspace, ledger)
            # Reject an active source before accepting the operation.
            with workspace_lock(source.directory, blocking=False):
                session = source._get_session(workspace_id)
                source._validate_workspace_revision(session, source.expected_revision)
                source.require_source_idle()
            _execute(operations, starter(api), terminal, directory)
    except BlockingIOError as exc:
        raise AgentApplicationError(
            "workspace_busy", "Workspace already has an active operation"
        ) from exc
    except RuntimeOperationIdempotencyConflict as exc:
        raise AgentApplicationError("idempotency_conflict", str(exc)) from exc


def cleanup_candidates(source: Path, prefix: str) -> int:
    if re.fullmatch(r"candidate-[0-9a-f]{16}-", prefix) is None:
        raise ValueError("Invalid candidate cleanup prefix")
    artifacts = source / ".agent" / "candidates"
    ledgers = source / ".agent" / "operations"

    paths = sorted(artifacts.glob(f"{prefix}*"))
    ids = {validate_candidate_id(path.name) for path in paths}
    # Include candidates that acquired their lock before materializing files.
    ids.update(
        validate_candidate_id(path.stem)
        for path in ledgers.glob(f"{prefix}*")
        if path.suffix in (".json", ".lock")
    )
    with ExitStack() as locks:
        for candidate in sorted(ids):
            locks.enter_context(candidate_lock(ledgers, candidate))
        locks.enter_context(workspace_lock(source, blocking=False))
        for path in paths:
            shutil.rmtree(path)
    return len(paths)


def _candidate_snapshot(source: ManagedWorkspace, directory: Path, candidate: str) -> dict:
    ledger = directory / f"{candidate}.json"
    key = candidate_operation_workspace_id(source.workspace_id, candidate)
    lock = candidate_lock(directory, candidate)
    if not ledger.is_file():
        raise AgentApplicationError("candidate_unavailable", "Candidate ledger is unavailable")
    reader = RuntimeOperationManager(lambda _event: None)
    try:
        with lock:
            reader.load_workspace_ledger(key, ledger)
    except BlockingIOError:
        reader.load_workspace_ledger(key, ledger, recover=False)
    return reader.workspace_snapshot(key)


def _execute(operations, start, terminal: threading.Event, directory: Path) -> None:
    cancel = threading.Event()

    def cancel_handler(_signum, _frame):
        cancel.set()

    previous = signal.signal(signal.SIGTERM, cancel_handler)
    try:
        operation = start()
        operation_id = operation["operationId"]
        _record("candidate_accepted", operation=operation)
        cancelled = False
        cancel_path = directory / f"{operation_id}.cancel"
        while operation["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
            if not cancelled and (cancel.is_set() or cancel_path.is_file()):
                operations.request_cancel(operation_id)
                cancelled = True
            terminal.wait(0.1)
            operation = operations.operation_status(operation_id)
        _record("candidate_terminal", operation=operation)
        cancel_path.unlink(missing_ok=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
