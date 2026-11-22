"""Adapt a single manifest-managed Workspace to the candidate executor."""

import json
import re
import shutil
import signal
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import chipcompiler
from chipcompiler.cli.project.current_location import resolve_current_location
from chipcompiler.data import load_workspace
from chipcompiler.engine.snapshot.store import read_engineering_snapshot_from_directory
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.runtime_processes import identity_is_live, validate_runtime_entry
from chipcompiler.utility.file import write_text_atomic
from chipcompiler.utility.workspace_lock import workspace_lock

from .candidate_resume import _validate_candidate_resume_request
from .data.candidate_artifacts import validate_candidate_id
from .operations import RuntimeOperationIdempotencyConflict, RuntimeOperationManager
from .requests import CandidateRerunRequest, CandidateResumeRequest, WorkspaceIdRequest
from .runtime_support import AgentApplicationError
from .workspace_api import (
    FlowAgentRuntimeApi,
    _validate_candidate_rerun_request,
    candidate_operation_workspace_id,
)


@dataclass(frozen=True)
class CandidateCommand:
    action: str
    project: str | None
    workspace: str
    request: dict


class ManagedWorkspace:
    def __init__(self, project: str | None, workspace: str, operations: RuntimeOperationManager):
        location = resolve_current_location(project, workspace, workspace_supported=True)
        self.project = Path(location.project or ".").resolve()
        self.workspace_id = workspace
        self.project_id = load_manifest(str(self.project)).project_id
        self.directory = self._registered_directory()
        self.operations = operations
        self.expected_revision: int | None = None

    def _registered_directory(self) -> Path:
        manifest = load_manifest(str(self.project))
        if manifest.project_id != self.project_id:
            raise AgentApplicationError("revision_conflict", "Project identity changed")
        entry = manifest.find_workspace(self.workspace_id)
        if entry is None:
            raise AgentApplicationError("workspace_not_declared", "Source Workspace is unavailable")
        path = Path(entry.workspace_path)
        if path.is_symlink() or not path.is_dir():
            raise AgentApplicationError("workspace_unavailable", "Source Workspace is unavailable")
        return path.resolve()

    def _get_session(self, workspace_id: str):
        if workspace_id != self.workspace_id:
            raise AgentApplicationError("workspace_unavailable", "Source Workspace is unavailable")
        if self._registered_directory() != self.directory:
            raise AgentApplicationError(
                "revision_conflict", "Source Workspace registration changed"
            )
        return SimpleNamespace(
            workspace_revision=read_engineering_snapshot_from_directory(self.directory)[
                "workspaceRevision"
            ]
        )

    @staticmethod
    def _validate_workspace_revision(session, expected: int | None) -> None:
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


def run_command(command: CandidateCommand) -> None:
    terminal = threading.Event()
    operations = RuntimeOperationManager(
        lambda event: terminal.set()
        if event.get("type") in {"operation.completed", "operation.cancelled", "operation.failed"}
        else None
    )
    source = ManagedWorkspace(command.project, command.workspace, operations)
    api = FlowAgentRuntimeApi(source)
    try:
        if command.action == "capabilities":
            capabilities = api.candidate_capabilities(WorkspaceIdRequest(command.workspace))
            _record("candidate_capabilities", eccVersion=chipcompiler.__version__, **capabilities)
            return
        if command.action == "status":
            candidate = validate_candidate_id(command.request["candidate_id"])
            directory = source.directory / ".agent" / "operations"
            _record("candidate_status", **_candidate_snapshot(source, directory, candidate))
            return
        if command.action == "cleanup":
            removed = _cleanup_candidates(source, command.request["prefix"])
            _record("candidate_cleanup", removed=removed)
            return
        if command.action == "retain":
            from .delivery import retain_candidate

            _record(
                "candidate_retained",
                **retain_candidate(
                    project=source.project,
                    project_id=source.project_id,
                    source=source.directory,
                    workspace_id=source.workspace_id,
                    **command.request,
                ),
            )
            return
        if command.action == "operation":
            _candidate_operation(
                source, command.request["operation_id"], cancel=command.request["cancel"]
            )
            return
        if command.action == "rerun":
            request = CandidateRerunRequest(command.workspace, **command.request)
            _validate_candidate_rerun_request(request)
            parent_ref = request.parent_candidate_root_ref
            start = partial(api.candidate_rerun, request)
        else:
            request = CandidateResumeRequest(command.workspace, **command.request)
            _validate_candidate_resume_request(request)
            parent_ref = None
            start = partial(api.candidate_resume, request)
        source.expected_revision = request.expected_workspace_revision
        if source.expected_revision is None:
            raise AgentApplicationError("invalid_request", "Workspace Revision is required")
        directory = source.directory / ".agent" / "operations"
        candidate_root = source.directory / ".agent" / "candidates"
        for path in (directory, candidate_root):
            if path.resolve() != path:
                raise AgentApplicationError(
                    "invalid_request", "Candidate directory is a symbolic link"
                )
        candidates = {request.candidate_id}
        if parent_ref is not None:
            parent = Path(parent_ref).name
            if parent == request.candidate_id:
                raise AgentApplicationError("invalid_request", "Candidate cannot be its own parent")
            candidates.add(parent)
        with ExitStack() as locks:
            for name in sorted(candidates):
                locks.enter_context(_candidate_lock(directory, name))
            ledger = directory / f"{request.candidate_id}.json"
            operation_workspace = candidate_operation_workspace_id(
                command.workspace, request.candidate_id
            )
            operations.load_workspace_ledger(operation_workspace, ledger)
            # Reject an active source before accepting the operation. The executor
            # also checks the source again under its lock when cloning.
            with workspace_lock(source.directory, blocking=False):
                session = source._get_session(command.workspace)
                source._validate_workspace_revision(session, source.expected_revision)
                source.require_source_idle()
            _execute(operations, start, terminal, directory)
    except BlockingIOError as exc:
        raise AgentApplicationError(
            "workspace_busy", "Workspace already has an active operation"
        ) from exc
    except RuntimeOperationIdempotencyConflict as exc:
        raise AgentApplicationError("idempotency_conflict", str(exc)) from exc


def _candidate_lock(directory: Path, candidate: str):
    if directory.resolve() != directory or any(
        (directory / f"{candidate}.{suffix}").is_symlink() for suffix in ("lock", "json")
    ):
        raise AgentApplicationError(
            "invalid_request", "Candidate operation path is a symbolic link"
        )
    return workspace_lock(directory / candidate, blocking=False)


def _cleanup_candidates(source: ManagedWorkspace, prefix: str) -> int:
    if re.fullmatch(r"candidate-[0-9a-f]{16}-", prefix) is None:
        raise ValueError("Invalid candidate cleanup prefix")
    artifacts = source.directory / ".agent" / "candidates"
    ledgers = source.directory / ".agent" / "operations"
    if any(path.resolve() != path for path in (artifacts, ledgers)):
        raise ValueError("Candidate directory is a symbolic link")

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
            locks.enter_context(_candidate_lock(ledgers, candidate))
        locks.enter_context(workspace_lock(source.directory, blocking=False))
        if source._registered_directory() != source.directory:
            raise AgentApplicationError(
                "revision_conflict", "Source Workspace registration changed"
            )
        if any(path.is_symlink() or not path.is_dir() for path in paths):
            raise ValueError("Candidate artifact path is not a regular directory")
        for path in paths:
            shutil.rmtree(path)
    return len(paths)


def _candidate_snapshot(source: ManagedWorkspace, directory: Path, candidate: str) -> dict:
    ledger = directory / f"{candidate}.json"
    key = candidate_operation_workspace_id(source.workspace_id, candidate)
    lock = _candidate_lock(directory, candidate)
    if not ledger.is_file():
        raise AgentApplicationError("candidate_unavailable", "Candidate ledger is unavailable")
    reader = RuntimeOperationManager(lambda _event: None)
    try:
        with lock:
            reader.load_workspace_ledger(key, ledger)
    except BlockingIOError:
        reader.load_workspace_ledger(key, ledger, recover=False)
    return reader.workspace_snapshot(key)


def _candidate_operation(source: ManagedWorkspace, operation_id: str, *, cancel: bool) -> None:
    if re.fullmatch(r"operation-[0-9a-f]{32}", operation_id) is None:
        raise ValueError("Invalid candidate operation ID")
    directory = source.directory / ".agent" / "operations"
    if directory.resolve() != directory:
        raise ValueError("Candidate directory is a symbolic link")
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


def _execute(operations, start, terminal: threading.Event, directory: Path) -> None:
    cancel = threading.Event()

    def cancel_handler(_signum, _frame):
        cancel.set()

    previous = signal.signal(signal.SIGTERM, cancel_handler)
    try:
        operation = start()
        operation_id = operation["operationId"]
        if operation["state"] == "interrupted":
            operation = {**operation, "state": "failed"}
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
