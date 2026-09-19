"""PDK root resolution-source disclosure for existing-workspace runs.

A fresh run persists the resolved absolute PDK root in the workspace's
``home/params.toml`` (``[pdk] root``), so a workspace resolves identically on
every machine. Workspaces created before that persistence (or hand-edited)
may leave the key empty: the loader then silently falls back to the
``CHIPCOMPILER_ICS55_PDK_ROOT`` / ``ICS55_PDK_ROOT`` environment variables,
and the same workspace resolves differently on different hosts. This module
detects that fallback for the CLI run paths and builds the warning record
naming the winning source.
"""

import os

_ENV_KEYS = ("CHIPCOMPILER_ICS55_PDK_ROOT", "ICS55_PDK_ROOT")


def pdk_root_env_fallback_warning(run_dir: str) -> dict | None:
    """Warning record when an existing workspace resolves its PDK root from
    the environment because the persisted root is empty/missing.

    None when the workspace pins a root, names a non-ics55 PDK (the
    environment variables only apply to ics55), or no environment variable
    resolves to an existing directory.
    """
    from chipcompiler.cli.core.records import warning_record
    from chipcompiler.cli.project.config import _pdk_root_from_env
    from chipcompiler.data.workspace_config import load_workspace_config

    try:
        payload = load_workspace_config(run_dir)
    except Exception:
        return None
    if str(payload.get("pdk_root") or "").strip():
        return None
    if str(payload.get("pdk") or "").strip().lower() not in ("", "ics55"):
        return None
    env_root = _pdk_root_from_env()
    if not env_root:
        return None
    source = next(key for key in _ENV_KEYS if os.environ.get(key, "").strip())
    return warning_record(
        "pdk_root_env_fallback",
        workspace=run_dir,
        source=source,
        resolved_root=env_root,
        reason="the workspace persists no [pdk] root; the PDK root resolves from "
        f"the {source} environment variable, so this workspace is not reproducible "
        "across machines without that variable; run 'ecc run --overwrite' to pin "
        "the resolved root into the workspace",
    )
