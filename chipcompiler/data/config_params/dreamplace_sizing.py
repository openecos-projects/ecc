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
        "place.diff_sizing_terminal_gr_sta_enabled",
        "dreamplace",
        ("diff_sizing_terminal_gr_sta_enabled",),
        0,
        type="int",
        range=(0, 1),
        applies="diff_sizing",
        description=(
            "re-read the final DEF and run terminal GR/RRR plus STA after diff sizing; "
            "disabled by default"
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
    config_param(
        "place.diff_sizing_timing_rc_mode",
        "dreamplace",
        ("diff_sizing_timing_rc_mode",),
        "gr",
        type="str",
        choices=("placement", "gr"),
        applies="diff_sizing",
        description=(
            "standalone diff_sizing timing RC source; placement uses the "
            "placement parasitics and gr uses the frozen GR snapshot"
        ),
    ),
    config_param(
        "place.diff_sizing_optimization_flows",
        "dreamplace",
        ("diff_sizing_optimization_flows",),
        None,
        type="json",
        applies="diff_sizing",
        description=(
            "ordered standalone diff_sizing phases: "
            "[action, rounds, [wns, tns, slew, cap], selection_percent]; "
            "action is quad, up, or down and percent is in (0, 100]; "
            "null selects one up phase with 50 rounds, diff_sizing_coefficients, "
            "and a shared 1% budget per round in lut_action mode"
        ),
    ),
    config_param(
        "place.timing_action_gradient_mode",
        "dreamplace",
        ("timing_action_gradient_mode",),
        "lut_action",
        type="str",
        choices=("off", "lut_action"),
        applies="diff_sizing",
        description="discrete sizing gradient mode; default lut_action, off is the legacy path",
    ),
    config_param(
        "place.timing_action_score_objective",
        "dreamplace",
        ("timing_action_score_objective",),
        "loss",
        type="str",
        choices=("loss", "tns", "wns"),
        applies="diff_sizing",
        description=(
            "objective differentiated for the local LUT action score; loss uses "
            "diff_sizing_coefficients, tns/wns select a single timing metric"
        ),
    ),
)
