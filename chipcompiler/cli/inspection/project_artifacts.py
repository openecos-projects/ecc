from pathlib import Path

from chipcompiler.engine.snapshot_limits import BoundedJsonObject, read_bounded_json_object


def read_workspace_artifact(root: Path, path: Path, max_bytes: int) -> BoundedJsonObject:
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return BoundedJsonObject("invalid", None)
        return read_bounded_json_object(path, max_bytes)
    except (OSError, RuntimeError, ValueError, OverflowError):
        return BoundedJsonObject("invalid", None)
