import hashlib
import json
from pathlib import Path

from ecc_experience.models import ExperienceError

JSON_LIMIT = 32 * 1024 * 1024
SMALL_EVIDENCE_LIMIT = 1024 * 1024


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path, limit: int = JSON_LIMIT) -> dict:
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ExperienceError(f"JSON exceeds {limit} bytes: {path}")
    try:
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        canonical_bytes(value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ExperienceError(f"Invalid JSON: {path}") from exc
    return value


def safe_child(root: Path, reference: str) -> Path:
    relative = Path(reference)
    if not reference or relative.is_absolute() or ".." in relative.parts:
        raise ExperienceError(f"Unsafe evidence reference: {reference}")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ExperienceError(f"Symlink evidence is not supported: {reference}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ExperienceError(f"Evidence escapes root: {reference}")
    return candidate


def file_digest(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise OSError(f"Evidence must be a regular file: {path}")
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while content := stream.read(1024 * 1024):
            checksum.update(content)
            size += len(content)
    return checksum.hexdigest(), size


def case_identity(case: dict) -> str:
    identity = {key: value for key, value in case.items() if key not in {"case_id", "collected_at"}}
    identity["source"] = {
        key: value for key, value in case["source"].items() if key != "workspace_root"
    }
    return f"case-{digest(identity)}"
