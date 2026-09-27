"""Durable identity records for manifest-managed ECC run processes."""

from __future__ import annotations

import hashlib
import math
import os
import re
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked

RUNTIME_PROCESS_SCHEMA_VERSION = 1
MAX_RUNTIME_PROCESSES = 4096
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9._:@+-]{1,128}\Z")


class RuntimeProcessError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    pgid: int
    process_start_id: str
    boot_id: str
    host_id: str


def normalize_run_id(value: str | None) -> str:
    if not value:
        return str(uuid.uuid4())
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise RuntimeProcessError("invalid_run_id", "run ID must be a UUID") from exc
    if str(parsed) != value:
        raise RuntimeProcessError("invalid_run_id", "run ID must use canonical UUID spelling")
    return str(parsed)


def normalize_runtime_id(value: str | None, *, default: str) -> str:
    result = value or default
    if not _SAFE_TOKEN.fullmatch(result) or not result.isascii():
        raise RuntimeProcessError(
            "invalid_runtime_id", "runtime ID must be a 1-128 byte ASCII safe token"
        )
    return result


def default_log_path(run_id: str) -> str:
    return f"home/run-logs/{run_id}.log"


def normalize_log_path(value: str | None, run_id: str) -> str:
    expected = default_log_path(run_id)
    result = value or expected
    if result != expected:
        raise RuntimeProcessError(
            "invalid_log_path", f"log file must be the run-scoped path {expected}"
        )
    _validate_relative_posix(result, field="log_path")
    return result


def create_run_log(workspace: str | Path, log_path: str) -> int:
    root = Path(workspace).resolve()
    target = root.joinpath(*PurePosixPath(log_path).parts)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        parent = target.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeProcessError("invalid_log_path", "run log escapes the Workspace") from exc
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(target, flags, 0o600)
    except OSError as exc:
        raise RuntimeProcessError("run_log_open_failed", str(exc)) from exc


def current_process_identity() -> ProcessIdentity:
    pid = os.getpid()
    return ProcessIdentity(
        pid=pid,
        pgid=os.getpgid(pid),
        process_start_id=_process_start_id(pid),
        boot_id=_boot_id(),
        host_id=_host_id(),
    )


def build_runtime_entry(
    project_dir: str | Path,
    workspace_path: str | Path,
    *,
    run_id: str,
    runtime_id: str,
    log_path: str,
    identity: ProcessIdentity | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    project = Path(project_dir).resolve()
    workspace = Path(workspace_path).resolve()
    registered_path = _registered_workspace_path(project, workspace)
    normalized_run_id = normalize_run_id(run_id)
    normalized_log = normalize_log_path(log_path, normalized_run_id)
    process = identity or current_process_identity()
    if process.pid != process.pgid:
        raise RuntimeProcessError(
            "invalid_process_group", "ECC run process must be its process group leader"
        )
    entry = {
        "schema_version": RUNTIME_PROCESS_SCHEMA_VERSION,
        "run_id": normalized_run_id,
        "pid": process.pid,
        "pgid": process.pgid,
        "process_start_id": process.process_start_id,
        "boot_id": process.boot_id,
        "host_id": process.host_id,
        "workspace_path": registered_path,
        "started_at": time.time() if started_at is None else started_at,
        "runtime_id": runtime_id,
        "log_path": normalized_log,
    }
    validate_runtime_entry(entry)
    return entry


def validate_runtime_entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeProcessError(
            "invalid_runtime_process", "runtime process entry is not a record"
        )
    required = {
        "schema_version",
        "run_id",
        "pid",
        "pgid",
        "process_start_id",
        "boot_id",
        "host_id",
        "workspace_path",
        "started_at",
        "runtime_id",
        "log_path",
    }
    if not required <= value.keys():
        raise RuntimeProcessError("invalid_runtime_process", "runtime process entry is incomplete")
    if value["schema_version"] != RUNTIME_PROCESS_SCHEMA_VERSION:
        raise RuntimeProcessError("invalid_runtime_process", "unsupported runtime process schema")
    normalize_run_id(value["run_id"])
    for field in ("pid", "pgid"):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] <= 0:
            raise RuntimeProcessError("invalid_runtime_process", f"{field} must be positive")
    if value["pid"] != value["pgid"]:
        raise RuntimeProcessError("invalid_runtime_process", "pid and pgid must match")
    for field in ("process_start_id", "boot_id", "host_id"):
        token = value[field]
        if not isinstance(token, str) or not _SAFE_TOKEN.fullmatch(token) or not token.isascii():
            raise RuntimeProcessError("invalid_runtime_process", f"invalid {field}")
    _validate_workspace_path(value["workspace_path"])
    _validate_relative_posix(value["log_path"], field="log_path")
    normalize_log_path(value["log_path"], value["run_id"])
    started_at = value["started_at"]
    if (
        not isinstance(started_at, (int, float))
        or isinstance(started_at, bool)
        or not math.isfinite(started_at)
        or started_at <= 0
    ):
        raise RuntimeProcessError("invalid_runtime_process", "started_at must be finite")
    normalize_runtime_id(value["runtime_id"], default="")
    return value


def register_runtime_process(
    project_dir: str | Path, workspace_id: str, entry: dict[str, Any], *, blocking: bool = True
) -> None:
    project = Path(project_dir).resolve()
    validated = validate_runtime_entry(entry)
    with manifest_lock(project, blocking=blocking):
        manifest = load_manifest(str(project))
        workspace = manifest.find_workspace(workspace_id)
        if workspace is None:
            raise RuntimeProcessError("workspace_not_declared", "Workspace is not registered")
        expected_path = _registered_workspace_path(project, Path(workspace.workspace_path))
        if expected_path != validated["workspace_path"]:
            raise RuntimeProcessError("workspace_identity_changed", "Workspace path changed")
        processes = manifest.raw.get("runtime_processes", {})
        if not isinstance(processes, dict) or len(processes) > MAX_RUNTIME_PROCESSES:
            raise RuntimeProcessError(
                "invalid_runtime_processes", "runtime process registry is invalid"
            )
        existing = processes.get(workspace_id)
        if existing is not None:
            if (
                isinstance(existing, dict)
                and existing.get("run_id") == entry["run_id"]
                and existing == entry
            ):
                return
            raise RuntimeProcessError(
                "workspace_running", "Workspace already has a runtime process"
            )

        def mutate(document: dict) -> None:
            current = document.setdefault("runtime_processes", {})
            if not isinstance(current, dict) or workspace_id in current:
                raise RuntimeProcessError(
                    "workspace_running", "Workspace already has a runtime process"
                )
            current[workspace_id] = dict(entry)

        if not update_manifest_locked(project, mutate):
            raise RuntimeProcessError(
                "runtime_registration_failed", "Project Manifest update failed"
            )


def unregister_runtime_process(
    project_dir: str | Path, workspace_id: str, run_id: str, *, blocking: bool = True
) -> bool:
    project = Path(project_dir).resolve()
    removed = False
    with manifest_lock(project, blocking=blocking):
        manifest = load_manifest(str(project))
        existing = manifest.raw.get("runtime_processes", {})
        if not isinstance(existing, dict):
            raise RuntimeProcessError(
                "invalid_runtime_processes", "runtime process registry is invalid"
            )
        value = existing.get(workspace_id)
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            return False

        def mutate(document: dict) -> None:
            nonlocal removed
            processes = document.get("runtime_processes", {})
            current = processes.get(workspace_id) if isinstance(processes, dict) else None
            if isinstance(current, dict) and current.get("run_id") == run_id:
                del processes[workspace_id]
                removed = True

        if not update_manifest_locked(project, mutate):
            raise RuntimeProcessError(
                "runtime_unregistration_failed", "Project Manifest update failed"
            )
    return removed


def read_runtime_process(
    project_dir: str | Path, workspace_id: str, run_id: str | None = None
) -> dict[str, Any]:
    manifest = load_manifest(str(Path(project_dir).resolve()))
    processes = manifest.raw.get("runtime_processes", {})
    value = processes.get(workspace_id) if isinstance(processes, dict) else None
    if value is None:
        raise RuntimeProcessError("process_not_found", "No runtime process is registered")
    entry = validate_runtime_entry(value)
    if run_id is not None and entry["run_id"] != run_id:
        raise RuntimeProcessError("process_not_found", "Registered run ID does not match")
    workspace = manifest.find_workspace(workspace_id)
    if workspace is None:
        raise RuntimeProcessError("invalid_runtime_process", "Runtime Workspace is not registered")
    expected_path = _registered_workspace_path(
        Path(project_dir).resolve(), Path(workspace.workspace_path)
    )
    if expected_path != entry["workspace_path"]:
        raise RuntimeProcessError(
            "invalid_runtime_process", "Runtime Workspace path does not match"
        )
    return entry


def identity_is_live(entry: dict[str, Any]) -> bool:
    value = validate_runtime_entry(entry)
    if value["host_id"] != _host_id() or value["boot_id"] != _boot_id():
        return False
    try:
        return (
            _process_start_id(value["pid"]) == value["process_start_id"]
            and os.getpgid(value["pid"]) == value["pgid"]
        )
    except (OSError, RuntimeProcessError):
        return False


def signal_runtime_process(entry: dict[str, Any], *, force: bool) -> None:
    value = validate_runtime_entry(entry)
    if not identity_is_live(value):
        raise RuntimeProcessError("process_not_found", "Runtime process identity is stale")
    pid = value["pid"]
    if force:
        if os.getpgid(pid) != pid or value["pgid"] != pid:
            raise RuntimeProcessError("process_identity_changed", "Runtime process group changed")
        os.killpg(pid, signal.SIGTERM)
        return
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        descriptor = os.pidfd_open(pid)
        try:
            if not identity_is_live(value):
                raise RuntimeProcessError("process_identity_changed", "Runtime process changed")
            signal.pidfd_send_signal(descriptor, signal.SIGUSR1)
        finally:
            os.close(descriptor)
    else:
        if not identity_is_live(value):
            raise RuntimeProcessError("process_identity_changed", "Runtime process changed")
        os.kill(pid, signal.SIGUSR1)


def _validate_relative_posix(value: Any, *, field: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeProcessError("invalid_runtime_process", f"invalid {field}")


def _validate_workspace_path(value: Any) -> None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RuntimeProcessError("invalid_runtime_process", "invalid workspace_path")
    path = PurePosixPath(value)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeProcessError("invalid_runtime_process", "invalid workspace_path")


def _registered_workspace_path(project: Path, workspace: Path) -> str:
    resolved = workspace.resolve()
    try:
        value = resolved.relative_to(project.resolve()).as_posix()
    except ValueError:
        value = resolved.as_posix()
    _validate_workspace_path(value)
    return value


def _process_start_id(pid: int) -> str:
    try:
        data = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        after_name = data[data.rfind(")") + 2 :].split()
        value = after_name[19]
    except (OSError, IndexError, UnicodeDecodeError) as exc:
        raise RuntimeProcessError("process_not_found", f"cannot read process {pid}") from exc
    if not value.isdigit():
        raise RuntimeProcessError("invalid_process_identity", "invalid Linux process start ID")
    return value


def _boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeProcessError("host_identity_unavailable", str(exc)) from exc
    if not _SAFE_TOKEN.fullmatch(value):
        raise RuntimeProcessError("host_identity_unavailable", "invalid Linux boot ID")
    return value


def _host_id() -> str:
    sources = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
    for path in sources:
        try:
            value = path.read_bytes().strip()
        except OSError:
            continue
        if value:
            return hashlib.sha256(value).hexdigest()
    raise RuntimeProcessError("host_identity_unavailable", "machine identity is unavailable")
