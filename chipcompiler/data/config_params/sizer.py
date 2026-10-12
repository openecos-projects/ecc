"""Public parameters for the ECC Sizer timing-optimization step."""

from .common import config_param

SCHEMAS = (
    config_param(
        "timing_opt.hold_margin",
        "sizer",
        ("hold_margin",),
        0.1,
        applies="timing_opt",
        description="Additional hold slack margin in ns for the Sizer hold-only pass.",
    ),
)
