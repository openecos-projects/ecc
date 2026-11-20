"""PDK root resolution-source disclosure for existing-workspace runs.

A fresh run persists the resolved absolute PDK root in the workspace's
``home/params.toml`` (``[pdk] root``), so a workspace resolves identically on
every machine. Workspaces created before that persistence (or hand-edited)
may leave the key empty: the loader then silently falls back to the
``ECC_PDK_ROOT`` environment variable,
and the same workspace resolves differently on different hosts. This module
detects that fallback for the CLI run paths and builds the warning record
naming the winning source.
"""


def pdk_root_env_fallback_warning(run_dir: str) -> dict | None:
    """Warning record when an existing workspace resolves its PDK root from
    the environment because the persisted root is empty/missing.

    None when the workspace pins a root or the variable names no existing directory.
    """
    from chipcompiler.cli.core.records import warning_record
    from chipcompiler.cli.project.config import _pdk_root_from_env
    from chipcompiler.data.workspace.config import load_workspace_config

    try:
        payload = load_workspace_config(run_dir)
    except Exception:
        return None
    if str(payload.get("pdk_root") or "").strip():
        return None
    env_root = _pdk_root_from_env()
    if not env_root:
        return None
    return warning_record(
        "pdk_root_env_fallback",
        workspace=run_dir,
        source="ECC_PDK_ROOT",
        resolved_root=env_root,
        reason="the workspace persists no [pdk] root; the PDK root resolves from "
        "the ECC_PDK_ROOT environment variable, so this workspace is not reproducible "
        "across machines without that variable; run 'ecc run --overwrite' to pin "
        "the resolved root into the workspace",
    )
