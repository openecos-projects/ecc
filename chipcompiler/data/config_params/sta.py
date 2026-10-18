from .common import config_param

SCHEMAS = (
    config_param(
        "sta.max_parallel_corners",
        "sta",
        ("max_parallel_corners",),
        1,
        applies="sta",
        description="Maximum simultaneous STA corners, reduced when memory headroom is low.",
        range=(1, 4),
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
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CH/liberty/ics55_LLSC_H7CH_ss_rcworst_1p08_125_nldm.lib",
                    "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_ss_1p08_2p97_125c.lib",
                ],
            },
            {
                "corner": "WCL",
                "temperature": -40,
                "path": [
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_cworst_1p08_m40_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_cworst_1p08_m40_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CH/liberty/ics55_LLSC_H7CH_ss_cworst_1p08_m40_nldm.lib",
                    "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_ss_1p08_2p97_125c.lib",
                ],
            },
            {
                "corner": "TYP",
                "temperature": 25,
                "path": [
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_typ_tt_1p2_25_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_typ_tt_1p2_25_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CH/liberty/ics55_LLSC_H7CH_typ_tt_1p2_25_nldm.lib",
                    "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_tt_1p2_3p3_25c.lib",
                ],
            },
            {
                "corner": "MIN",
                "temperature": -40,
                "path": [
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ff_rcbest_1p32_m40_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ff_rcbest_1p32_m40_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CH/liberty/ics55_LLSC_H7CH_ff_rcbest_1p32_m40_nldm.lib",
                    "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_ff_1p32_3p63v_0c.lib",
                ],
            },
            {
                "corner": "ML",
                "temperature": 125,
                "path": [
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ff_cbest_1p32_125_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ff_cbest_1p32_125_nldm.lib",
                    "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CH/liberty/ics55_LLSC_H7CH_ff_cbest_1p32_125_nldm.lib",
                    "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_ff_1p32_3p63v_0c.lib",
                ],
            },
        ],
        applies="sta",
        description=(
            "Liberty corner groups analyzed by STA. Each entry is "
            "{corner, temperature, path}; relative paths are expanded "
            "against the PDK root on config refresh. ICS55 IO libraries use "
            "SS/125 C, TT/25 C and FF/0 C; group temperatures remain unchanged."
        ),
        type="json",
    ),
    config_param(
        "sta.signoff",
        "sta",
        ("signoff",),
        [
            {
                "MAX": ["Cworst", "RCworst"],
                "WCL": ["Cworst", "RCworst"],
                "TYP": ["TYPICAL"],
                "MIN": ["Cworst", "RCworst", "Cbest", "RCbest"],
                "ML": ["Cworst", "RCworst", "Cbest", "RCbest"],
            }
        ],
        applies="sta",
        description="Liberty-corner to RC-corner combinations analyzed for timing signoff.",
        type="json",
    ),
)
