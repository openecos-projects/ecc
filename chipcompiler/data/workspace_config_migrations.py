"""In-place migrations for structured ``home/params.toml`` files."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_workspace_config_to_v2(workspace_dir: Path) -> None:
    """Rewrite a version-1 workspace config without persisted mirror fields.

    The canonical flat payload remains unchanged after loading. Only the TOML
    representation changes: identity keys are kept in ``[design]``/``[pdk]``
    and equal DreamPlace semantic mirrors are removed in favor of their
    top-level workspace parameters. Conflicting nested values remain explicit
    overrides. A failed migration leaves the source file untouched so the
    workspace can still be opened and retried later.
    """
    from .workspace_config import (
        _decode_workspace_config,
        _stage_config_bytes,
        _unlink_best_effort,
        render_workspace_config,
        workspace_config_path,
    )

    workspace_root = Path(workspace_dir).resolve()
    home_dir = workspace_root / "home"
    config_path = workspace_config_path(workspace_root)
    if not config_path.is_file():
        return
    if home_dir.is_symlink() or config_path.is_symlink():
        logger.warning("params.toml v2 migration refused through a symlink: %s", config_path)
        return

    try:
        payload = _decode_workspace_config(config_path, workspace_root)
        flow = payload.pop("_flow", {})
        content = render_workspace_config(workspace_root, payload, flow or None)
    except (OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "params.toml v2 migration deferred (render failed): %s: %s", config_path, exc
        )
        return

    candidate = _stage_config_bytes(config_path, content)
    if candidate is None:
        logger.warning("params.toml v2 migration deferred (rewrite failed): %s", config_path)
        return
    try:
        _decode_workspace_config(candidate, workspace_root)
        os.replace(candidate, config_path)
    except Exception as exc:
        logger.warning(
            "params.toml v2 migration deferred (install failed): %s: %s", config_path, exc
        )
        _unlink_best_effort(candidate)
