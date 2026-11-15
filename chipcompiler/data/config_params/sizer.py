"""Public parameters for the ECC Sizer timing-optimization step."""

from .common import config_param

SCHEMAS = (
    config_param(
        "timing_opt.hold_margin",
        "sizer",
        ("hold_stage", "hold_margin"),
        0.04,
        applies="timing_optimization",
        description="Additional hold slack margin in ns for the Sizer hold-only pass.",
    ),
    config_param(
        "timing_opt.hold_rc_mode",
        "sizer",
        ("hold_stage", "rc_mode"),
        "global_routing",
        applies="timing_optimization",
        choices=("global_routing", "placement"),
        description="Parasitic model used by the Sizer hold-only pass.",
    ),
    config_param(
        "timing_opt.global_routing_rc",
        "sizer",
        ("hold_stage", "global_routing_rc"),
        {},
        applies="timing_opt",
        description=(
            "Per-layer and via RC written to the hold-stage setRCFile. Values "
            "use ohm/um, pF/um and ohm. Supply characterized data "
            "from the selected PDK profile."
        ),
        type="json",
    ),
    config_param(
        "timing_opt.placement_wire_rc_corner",
        "sizer",
        ("hold_stage", "placement_wire_rc", "corner"),
        "",
        applies="timing_opt",
        description=(
            "Source corner label for the configured placement unit wire RC; "
            "must match the selected PDK profile."
        ),
    ),
    config_param(
        "timing_opt.placement_wire_resistance_ohm_per_um",
        "sizer",
        ("hold_stage", "placement_wire_rc", "resistance_ohm_per_um"),
        0.0,
        applies="timing_opt",
        description=(
            "Placement wire resistance in ohm/um for the selected hold-pass parasitic model."
        ),
    ),
    config_param(
        "timing_opt.placement_wire_capacitance_pf_per_um",
        "sizer",
        ("hold_stage", "placement_wire_rc", "capacitance_pf_per_um"),
        0.0,
        applies="timing_opt",
        description=(
            "Placement wire capacitance in pF/um for the selected hold-pass parasitic model."
        ),
    ),
)
