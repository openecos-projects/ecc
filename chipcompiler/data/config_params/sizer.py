"""Public parameters for the ECC Sizer timing-optimization step."""

from .common import config_param

SCHEMAS = (
    config_param(
        "timing_opt.hold_margin",
        "sizer",
        ("hold_stage", "hold_margin"),
        0.04,
        applies="timing_opt",
        description="Additional hold slack margin in ns for the Sizer hold-only pass.",
    ),
    config_param(
        "timing_opt.hold_rc_mode",
        "sizer",
        ("hold_stage", "rc_mode"),
        "global_routing",
        applies="timing_opt",
        choices=("global_routing", "placement"),
        description="Parasitic model used by the Sizer hold-only pass.",
    ),
    config_param(
        "timing_opt.global_routing_rc",
        "sizer",
        ("hold_stage", "global_routing_rc"),
        {
            "corner": "MIN_m40/Cbest",
            "layers": {
                "MET1": {
                    "resistance_ohm_per_um": 1.430921150,
                    "capacitance_pf_per_um": 0.00012205,
                },
                "MET2": {
                    "resistance_ohm_per_um": 1.053236741,
                    "capacitance_pf_per_um": 0.00011035,
                },
                "MET3": {
                    "resistance_ohm_per_um": 1.053236741,
                    "capacitance_pf_per_um": 0.00011035,
                },
                "MET4": {
                    "resistance_ohm_per_um": 1.053236741,
                    "capacitance_pf_per_um": 0.00011035,
                },
                "MET5": {
                    "resistance_ohm_per_um": 1.053236741,
                    "capacitance_pf_per_um": 0.0001130,
                },
            },
            "vias": {
                "CT": {"resistance_ohm": 30.0},
                "VIA1": {"resistance_ohm": 2.0},
                "VIA2": {"resistance_ohm": 2.0},
                "VIA3": {"resistance_ohm": 2.0},
                "VIA4": {"resistance_ohm": 2.0},
            },
        },
        applies="timing_opt",
        description=(
            "Per-layer and via RC written to the hold-stage setRCFile. Values "
            "use ohm/um, pF/um and ohm. Default wire capacitances are scaled "
            "by 0.5 from the CX55 MIN_m40/Cbest source table."
        ),
        type="json",
    ),
    config_param(
        "timing_opt.placement_wire_rc_corner",
        "sizer",
        ("hold_stage", "placement_wire_rc", "corner"),
        "MIN_m40/Cbest",
        applies="timing_opt",
        description=(
            "Source corner label for the configured placement unit wire RC; "
            "the CX55 default is MIN_m40/Cbest."
        ),
    ),
    config_param(
        "timing_opt.placement_wire_resistance_ohm_per_um",
        "sizer",
        ("hold_stage", "placement_wire_rc", "resistance_ohm_per_um"),
        1.053236741,
        applies="timing_opt",
        description=(
            "Placement wire resistance in ohm/um for the CX55 MIN_m40/Cbest "
            "hold-pass parasitic model."
        ),
    ),
    config_param(
        "timing_opt.placement_wire_capacitance_pf_per_um",
        "sizer",
        ("hold_stage", "placement_wire_rc", "capacitance_pf_per_um"),
        0.00011035,
        applies="timing_opt",
        description=(
            "Placement wire capacitance in pF/um for the CX55 MIN_m40/Cbest "
            "hold-pass parasitic model, scaled by 0.5 from the source table."
        ),
    ),
)
