"""Public coefficients for the standalone DreamPlace diff-sizing step."""

from .common import config_param

DEFAULT_DIFF_SIZING_COEFFICIENTS = {"wns": 500.0, "tns": 5.0, "cap": 1.0, "slew": 1.0}

SCHEMAS = (
    config_param(
        "place.diff_sizing_continuous_steps",
        "dreamplace",
        ("diff_sizing_continuous_steps",),
        0,
        type="int",
        range=(0, 1000),
        applies="diff_sizing",
        description=(
            "standalone S50 continuous real-size sizing steps before discrete sizing; "
            "zero starts directly from the input masters with discrete gradient-topk sizing"
        ),
    ),
    config_param(
        "place.diff_sizing_coefficients",
        "dreamplace",
        ("diff_sizing_coefficients",),
        DEFAULT_DIFF_SIZING_COEFFICIENTS,
        applies="diff_sizing",
        description=(
            "standalone S50 WNS/TNS/cap/slew coefficients; finite, nonnegative values "
            "with outer timing weight 1; partial overrides retain the remaining defaults"
        ),
    ),
)
