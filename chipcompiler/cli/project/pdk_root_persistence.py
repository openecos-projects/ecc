"""PDK root persistence requirement for existing-workspace runs.

A fresh run persists the resolved absolute PDK root in the workspace's
``home/params.toml`` (``[pdk] root``), so a workspace resolves identically on
every machine. Workspaces created before that persistence (or hand-edited)
may leave the key empty, in which case re-running them would silently
resolve a possibly different root from ``ECC_PDK_ROOT`` or the repository
default. This module blocks that re-run with a clear error instead of
reproducing the workspace differently depending on today's environment.
"""

_BUILTIN_ENV_FALLBACK_PDKS = ("", "ics55", "sg13g2")


def missing_pdk_root_reason(run_dir: str) -> str | None:
    """Reason an existing workspace cannot run, or None when it may.

    Blocks only when the persisted root is empty/missing and the workspace
    names a built-in PDK that resolves its root from ECC_PDK_ROOT (the
    persistence requirement does not apply to externally configured PDKs,
    which carry their own root).
    """
    from chipcompiler.data.workspace.config import load_workspace_config

    try:
        payload = load_workspace_config(run_dir)
    except Exception:
        return None
    if str(payload.get("pdk_root") or "").strip():
        return None
    if str(payload.get("pdk") or "").strip().lower() not in _BUILTIN_ENV_FALLBACK_PDKS:
        return None
    return (
        "the workspace persists no [pdk] root; re-running it would resolve the root from "
        "ECC_PDK_ROOT or the repository default, which may differ from the original run; "
        "run 'ecc run --overwrite' to pin the resolved root into the workspace"
    )
