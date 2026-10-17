"""Serialize reversible model activation without modifying design configuration."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ecc_experience.files import read_json, safe_child
from ecc_experience.modeling.predict import read_model_release
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

REGISTRY_SCHEMA = "ecc-experience-model-registry/1"
_RELEASE_ID = re.compile(r"model-release-[0-9a-f]{64}\Z")


def promote(release: str | Path, registry: str | Path) -> dict:
    payload = read_model_release(release)
    root = _root(registry)
    with _writer(root):
        active_path = safe_child(root, "active.json")
        active = _read_active(active_path)
        if active:
            _read_release(root, active["active_release_id"])
        destination = _release_path(root, payload["release_id"])
        if destination.exists():
            existing = _read_release(root, payload["release_id"])
            if _identity(existing) != _identity(payload):
                raise invalid("Registry release already exists with different content")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_plan(destination, payload)
        if active and active["active_release_id"] == payload["release_id"]:
            return {"status": "already_active", "release_id": payload["release_id"]}
        history = [*active["history"], active["active_release_id"]] if active else []
        _activate(active_path, payload["release_id"], history)
    return {"status": "promoted", "release_id": payload["release_id"], "registry": str(root)}


def rollback(registry: str | Path, release_id: str | None = None) -> dict:
    root = _root(registry)
    with _writer(root):
        active_path = safe_child(root, "active.json")
        active = _read_active(active_path)
        if active is None:
            raise invalid("Model registry has no active release")
        target = release_id or (active["history"][-1] if active["history"] else None)
        if target is None:
            raise ExperienceError(
                "Model registry has no rollback target", code="experience_model_registry_empty"
            )
        _read_release(root, target)
        if target == active["active_release_id"]:
            return {"status": "already_active", "release_id": target, "registry": str(root)}
        history = [item for item in active["history"] if item != target]
        _activate(active_path, target, [*history, active["active_release_id"]])
    return {"status": "rolled_back", "release_id": target, "registry": str(root)}


def status(registry: str | Path) -> dict:
    root = _root(registry)
    active = _read_active(safe_child(root, "active.json"))
    if active is None:
        return {"status": "empty", "registry": str(root), "active_release_id": None, "history": []}
    release = _read_release(root, active["active_release_id"])
    return {
        "status": "active",
        "registry": str(root),
        "active_release_id": active["active_release_id"],
        "release": str(_release_path(root, active["active_release_id"])),
        "model_id": release["model_id"],
        "target": release["model"]["target"],
        "through_step": release["model"]["through_step"],
        "training_dataset_id": release["model"]["training_dataset_id"],
        "history": active["history"],
        "safe_to_apply": False,
    }


def _root(value: str | Path) -> Path:
    root = Path(value).expanduser().absolute()
    if root.is_file() or root.is_symlink():
        raise invalid("Model registry path must be a directory")
    return root.resolve()


@contextmanager
def _writer(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock = safe_child(root, ".write-lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ExperienceError(
            "Another writer holds the model registry lock", code="experience_store_busy"
        ) from exc
    try:
        yield
    finally:
        lock.rmdir()


def _release_path(root: Path, release_id: str) -> Path:
    if not _RELEASE_ID.fullmatch(release_id):
        raise invalid("Invalid model registry release ID")
    return safe_child(root, f"releases/{release_id}.json")


def _read_release(root: Path, release_id: str) -> dict:
    release = read_model_release(_release_path(root, release_id))
    if release["release_id"] != release_id:
        raise invalid("Registry release filename does not match its identity")
    return release


def _read_active(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = read_json(path)
    if (
        payload.get("schema") != REGISTRY_SCHEMA
        or not isinstance(payload.get("active_release_id"), str)
        or not _RELEASE_ID.fullmatch(payload["active_release_id"])
        or not isinstance(payload.get("history"), list)
        or len(payload["history"]) > 100
        or not all(
            isinstance(item, str) and _RELEASE_ID.fullmatch(item) for item in payload["history"]
        )
    ):
        raise invalid("Model registry active pointer is invalid")
    return payload


def _activate(path: Path, release_id: str, history: list[str]) -> None:
    write_plan(
        path,
        {
            "schema": REGISTRY_SCHEMA,
            "active_release_id": release_id,
            "history": history[-100:],
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _identity(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "published_at"}


def invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_model_registry_invalid")
