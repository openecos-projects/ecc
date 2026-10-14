"""Project-scoped experience recording configuration and append-only outbox."""

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ecc_experience.files import canonical_bytes, read_json, safe_child
from ecc_experience.models import ExperienceError

CONFIG_RELATIVE = ".ecc/experience.json"
OUTBOX_RELATIVE = ".ecc/experience/outbox"
CONFIG_SCHEMA_VERSION = 1
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_EVENT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ExperienceConfig:
    enabled: bool
    mode: str
    store: str
    updated_at: str


def _project_root(project: str | Path) -> Path:
    requested = Path(project).expanduser()
    if not requested.is_dir():
        raise ExperienceError(
            f"Project does not exist: {requested}", code="experience_project_invalid"
        )
    if requested.is_symlink():
        raise ExperienceError(
            "Project root must not be a symlink", code="experience_project_invalid"
        )
    return requested.resolve()


def _config_path(project: str | Path) -> Path:
    return safe_child(_project_root(project), CONFIG_RELATIVE)


def _outbox_path(project: str | Path) -> Path:
    return safe_child(_project_root(project), OUTBOX_RELATIVE)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _validate_config(data: object) -> ExperienceConfig:
    if not isinstance(data, dict):
        raise ExperienceError("Experience configuration must be an object")
    if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ExperienceError("Unsupported experience configuration schema")
    if type(data.get("enabled")) is not bool or data.get("mode") != "record":
        raise ExperienceError("Invalid experience configuration")
    store = data.get("store")
    updated_at = data.get("updated_at")
    if not isinstance(store, str) or not store or not isinstance(updated_at, str) or not updated_at:
        raise ExperienceError("Invalid experience configuration")
    return ExperienceConfig(
        enabled=data["enabled"], mode=data["mode"], store=store, updated_at=updated_at
    )


def load_config(project: str | Path) -> ExperienceConfig | None:
    path = _config_path(project)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ExperienceError("Experience configuration is oversized")
        return _validate_config(read_json(path, _MAX_CONFIG_BYTES))
    except OSError as exc:
        raise ExperienceError("Unable to read experience configuration") from exc


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(canonical_bytes(data))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def set_enabled(project: str | Path, *, store: str | Path, enabled: bool) -> ExperienceConfig:
    root = _project_root(project)
    store_path = Path(store).expanduser().absolute().resolve()
    if store_path == root or store_path.is_relative_to(root) or root.is_relative_to(store_path):
        raise ExperienceError(
            "Experience store must be outside the project", code="experience_project_invalid"
        )
    config = ExperienceConfig(
        enabled=enabled,
        mode="record",
        store=str(store_path),
        updated_at=_timestamp(),
    )
    _write_json(
        _config_path(root),
        {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "enabled": config.enabled,
            "mode": config.mode,
            "store": config.store,
            "updated_at": config.updated_at,
        },
    )
    return config


def disable(project: str | Path) -> ExperienceConfig:
    current = load_config(project)
    if current is None:
        raise ExperienceError(
            "Experience recording is not configured", code="experience_not_configured"
        )
    return set_enabled(project, store=current.store, enabled=False)


def status(project: str | Path) -> dict:
    root = _project_root(project)
    config = load_config(root)
    outbox = _outbox_path(root)
    pending = 0
    invalid = 0
    if outbox.exists():
        for path in outbox.iterdir():
            if path.is_symlink() or not path.is_file():
                invalid += 1
                continue
            if path.name.endswith(".json"):
                pending += 1
    return {
        "configured": config is not None,
        "enabled": config.enabled if config else False,
        "mode": config.mode if config else None,
        "store": config.store if config else None,
        "config": str(_config_path(root)),
        "outbox": {"pending": pending, "invalid": invalid, "directory": str(outbox)},
    }


class ExperienceRecorder:
    """Write small execution facts without entering the flow commit failure domain."""

    def __init__(self, project: str | Path, workspace: str | Path, config: ExperienceConfig):
        self.project = _project_root(project)
        self.workspace = Path(workspace).expanduser().resolve()
        self.config = config
        self.attempt_id = f"attempt-{uuid4().hex}"
        self._sequence = 0

    def start(self, *, intent: str, requested_steps: tuple[str, ...] = ()) -> None:
        self._write(
            "attempt_started",
            {
                "intent": intent,
                "requested_steps": list(requested_steps),
                "workspace": str(self.workspace),
            },
        )

    def committed_step(self, snapshot: dict, step, state, error: str | None = None) -> None:
        step_name = str(getattr(step, "name", ""))
        step_tool = str(getattr(step, "tool", ""))
        flow_step = next(
            (
                item
                for item in snapshot.get("flow", {}).get("steps", [])
                if isinstance(item, dict) and item.get("name") == step_name
            ),
            {},
        )
        self._write(
            "step_committed",
            {
                "workspace_id": snapshot.get("workspaceId"),
                "workspace_revision": snapshot.get("workspaceRevision"),
                "snapshot_schema": snapshot.get("schemaVersion"),
                "snapshot_cause": snapshot.get("cause"),
                "snapshot_digest": _snapshot_digest(snapshot),
                "step": step_name,
                "tool": step_tool,
                "state": getattr(state, "value", str(state)),
                "error": error,
                "resource": {
                    "elapsed_seconds": _runtime_seconds(flow_step.get("runtime")),
                    "peak_memory_mb": _number(flow_step.get("peak memory (mb)")),
                    "scope": "flow_step_ledger",
                    "status": "available"
                    if flow_step.get("runtime") or flow_step.get("peak memory (mb)")
                    else "unavailable",
                },
            },
        )

    def finish(self, *, status: str, error: str | None = None) -> None:
        self._write("attempt_finished", {"status": status, "error": error})

    def _write(self, event: str, payload: dict) -> None:
        outbox = _outbox_path(self.project)
        outbox.mkdir(parents=True, exist_ok=True)
        sequence = self._sequence
        self._sequence += 1
        data = {
            "schema_version": 1,
            "event_id": f"event-{uuid4().hex}",
            "attempt_id": self.attempt_id,
            "sequence": sequence,
            "event": event,
            "created_at": _timestamp(),
            **payload,
        }
        encoded = canonical_bytes(data)
        if len(encoded) > _MAX_EVENT_BYTES:
            raise ExperienceError("Experience event is oversized")
        path = outbox / f"{self.attempt_id}-{sequence:06d}.json"
        _write_json(path, data)


def recorder_for(project: str | Path, workspace: str | Path) -> ExperienceRecorder | None:
    config = load_config(project)
    if config is None or not config.enabled:
        return None
    return ExperienceRecorder(project, workspace, config)


def _number(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _runtime_seconds(value) -> float | None:
    if not isinstance(value, str):
        return _number(value)
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (float(part) for part in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _snapshot_digest(snapshot: dict) -> str | None:
    from ecc_experience.files import digest

    try:
        return digest(snapshot)
    except (TypeError, ValueError):
        return None
