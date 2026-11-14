import os


def complete_ics55_pdk_available(pdk_root: str = "") -> bool:
    """Return true when the real ICS55 PDK files required by integration tests exist."""
    root = _resolve_ics55_root(pdk_root)
    from chipcompiler.data.pdk import PDK_ICS55

    pdk = PDK_ICS55(root)
    return all(path and path.is_file() for path in [pdk.tech, *pdk.lefs, *pdk.libs])


def _resolve_ics55_root(pdk_root: str = "") -> str:
    explicit = (pdk_root or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))

    env_root = (
        os.environ.get("CHIPCOMPILER_ICS55_PDK_ROOT", "").strip()
        or os.environ.get("ICS55_PDK_ROOT", "").strip()
    )
    if env_root:
        return os.path.abspath(os.path.expanduser(env_root))

    current_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(current_dir)
    return os.path.join(os.path.dirname(repo_root), "pdk", "icsprout55-pdk")
