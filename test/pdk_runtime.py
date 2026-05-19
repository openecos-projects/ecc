from __future__ import annotations

import os


def complete_ics55_pdk_available(pdk_root: str = "") -> bool:
    """Return true when the real ICS55 PDK files required by integration tests exist."""
    root = _resolve_ics55_root(pdk_root)
    stdcell_dir = os.path.join(root, "IP", "STD_cell", "ics55_LLSC_H7C_V1p10C100")
    required = [
        os.path.join(root, "prtech", "techLEF", "N551P6M_ecos.lef"),
        os.path.join(stdcell_dir, "ics55_LLSC_H7CR", "lef", "ics55_LLSC_H7CR_ecos.lef"),
        os.path.join(stdcell_dir, "ics55_LLSC_H7CL", "lef", "ics55_LLSC_H7CL_ecos.lef"),
        os.path.join(
            stdcell_dir,
            "ics55_LLSC_H7CR",
            "liberty",
            "ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib",
        ),
        os.path.join(
            stdcell_dir,
            "ics55_LLSC_H7CL",
            "liberty",
            "ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib",
        ),
    ]
    return all(os.path.isfile(path) for path in required)


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
    return os.path.join(repo_root, "chipcompiler", "thirdparty", "icsprout55-pdk")
