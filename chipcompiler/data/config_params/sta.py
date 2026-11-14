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
        [
            {
                "corner": "MAX",
                "temperature": 125,
                "path": [
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_HVT/liberty/ICsprout55_9THVT_ss_v1p08_125c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_LVT/liberty/ICsprout55_9TLVT_ss_v1p08_125c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_SVT/liberty/ICsprout55_9TSVT_ss_v1p08_125c_basic_nldm.lib",
                ],
            },
            {
                "corner": "WCL",
                "temperature": -40,
                "path": [
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_HVT/liberty/ICsprout55_9THVT_ss_v1p08_-40c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_LVT/liberty/ICsprout55_9TLVT_ss_v1p08_-40c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_SVT/liberty/ICsprout55_9TSVT_ss_v1p08_-40c_basic_nldm.lib",
                ],
            },
            {
                "corner": "TYP",
                "temperature": 25,
                "path": [
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_HVT/liberty/ICsprout55_9THVT_tt_v1p2_25c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_LVT/liberty/ICsprout55_9TLVT_tt_v1p2_25c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_SVT/liberty/ICsprout55_9TSVT_tt_v1p2_25c_basic_nldm.lib",
                ],
            },
            {
                "corner": "MIN",
                "temperature": -40,
                "path": [
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_HVT/liberty/ICsprout55_9THVT_ff_v1p32_-40c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_LVT/liberty/ICsprout55_9TLVT_ff_v1p32_-40c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_SVT/liberty/ICsprout55_9TSVT_ff_v1p32_-40c_basic_nldm.lib",
                ],
            },
            {
                "corner": "ML",
                "temperature": 125,
                "path": [
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_HVT/liberty/ICsprout55_9THVT_ff_v1p32_125c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_LVT/liberty/ICsprout55_9TLVT_ff_v1p32_125c_basic_nldm.lib",
                    "/IP/STD_cell/ICsprout55_SC9T_BASIC_SVT/liberty/ICsprout55_9TSVT_ff_v1p32_125c_basic_nldm.lib",
                ],
            },
        ],
        applies="sta",
        description=(
            "Liberty corner groups analyzed by STA. Each entry is "
            "{corner, temperature, path}; relative paths are expanded "
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
        [
            {
                "TYP": ["TYPICAL"],
                "MIN": ["Cworst", "RCworst", "Cbest", "RCbest"],
            }
        ],
        applies="sta",
        description="Liberty-corner to RC-corner combinations analyzed for timing signoff.",
        type="json",
    ),
)
