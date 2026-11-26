from .common import config_param

SCHEMAS = (
    config_param(
        "sta.max_parallel_corners",
        "sta",
        ("max_parallel_corners",),
        1,
        applies="sta",
        description=(
            "Maximum simultaneous STA corners, capped by the configured signoff corner "
            "combinations, available CPUs, and memory headroom."
        ),
        range=(1, None),
    ),
    config_param(
        "sta.liberty",
        "sta",
        ("liberty",),
        [],
        applies="sta",
        description=(
            "Liberty corner groups analyzed by STA. Each entry is "
            "{corner, temperature, path}; optional rc_corner selects a complete "
            "group for that PVT/RC pair instead of the PVT-only default. "
            "Optional min_path lists explicit early macro models paired with the "
            "late models in path; other cells share their ordinary libraries. "
            "Relative paths are expanded "
            "against the PDK root on config refresh. ICS55 IO libraries are "
            "not included by default. The v2 standard-cell corners use the "
            "1.2 V domain (SS 1.08 V, TT 1.2 V, FF 1.32 V)."
        ),
        type="json",
    ),
    config_param(
        "sta.signoff",
        "sta",
        ("signoff",),
        [],
        applies="sta",
        description=(
            "Liberty-corner to RC-corner combinations analyzed for timing signoff. "
            "Corner names are PDK-defined strings; ICS55 supplies TYP/MIN by default."
        ),
        type="json",
    ),
)
