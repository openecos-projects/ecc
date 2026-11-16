"""Bound completed Replay history while protecting current and unfinished attempts."""

import json
import logging
import re
import shutil

from chipcompiler.tools.replay_storage import read_pointer, within
from chipcompiler.utility.workspace_lock import workspace_lock

logger = logging.getLogger(__name__)


def prune_completed(root):
    """Keep the current result and one completed predecessor; never follow links."""
    retired = []
    try:
        with workspace_lock(root):
            current = read_pointer(root)
            if current.get("status") not in {"complete", "diagnostic_only"}:
                return
            attempts = root / "attempts"
            completed = []
            for path in attempts.iterdir():
                if (
                    path.is_symlink()
                    or not path.is_dir()
                    or not re.fullmatch(r"[0-9a-f]{32}", path.name)
                ):
                    continue
                manifest = path / "manifest.json"
                if manifest.is_symlink() or not manifest.is_file():
                    continue
                data = json.loads(manifest.read_text())
                if not isinstance(data, dict):
                    continue
                if (
                    data.get("attempt_id") == path.name
                    and data.get("status") in {"complete", "diagnostic_only"}
                    and path.name != current.get("attempt_id")
                ):
                    completed.append((manifest.stat().st_mtime_ns, path))
            completed.sort(key=lambda item: item[0], reverse=True)
            garbage = root / ".retired"
            if garbage.is_symlink():
                raise ValueError("Replay retirement directory is a symlink")
            garbage.mkdir(exist_ok=True)
            within(root, garbage)
            retired.extend(
                path
                for path in garbage.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and re.fullmatch(r"[0-9a-f]{32}", path.name)
            )
            for _, path in completed[1:]:
                destination = garbage / path.name
                if destination.exists():
                    continue
                path.rename(destination)
                retired.append(destination)
        # Large deletions never hold the publication lock. Open viewers reject
        # a changed current pointer before seeking into an older recording.
        for path in retired:
            shutil.rmtree(path)
    except (OSError, ValueError):
        logger.warning("Replay history cleanup deferred", exc_info=True)
