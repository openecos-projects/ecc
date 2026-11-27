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
        choices=("placement", "gr", "spef"),
        applies="diff_sizing",
        description=(
            "standalone diff_sizing timing RC source; placement uses placement "
            "parasitics, gr uses the frozen GR snapshot, and spef uses extracted "
            "post-route SPEF"
        ),
    ),
    config_param(
        "place.diff_sizing_spef_input",
        "dreamplace",
        ("spef_input",),
        "",
        type="str",
        applies="diff_sizing",
        description=(
            "post-route .spef or .spef.gz file path consumed when "
            "place.diff_sizing_timing_rc_mode=spef"
        ),
    ),
    config_param(
        "place.diff_sizing_spef_coupling_cap_scale",
        "dreamplace",
        ("spef_coupling_cap_scale",),
        1.0,
        type="float",
        range=(0.0, None),
        applies="diff_sizing",
        description=(
            "nonnegative coupling-capacitor scale factor in SPEF mode; 1.0 folds "
            "1x grounded equivalent coupling cap without double-counting symmetric D_NETs"
        ),
    ),
    config_param(
        "place.diff_sizing_spef_reconcile_lumped_cap",
        "dreamplace",
        ("spef_reconcile_lumped_cap",),
        0,
        type="int",
        range=(0, 1),
        applies="diff_sizing",
        description=(
            "distribute positive (*D_NET total cap - unscaled *CAP sum) equally across "
            "each net's pin nodes in SPEF mode to recover omitted pin-node wire cap"
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
            "action is quad, up, down, vt, vt_fast, or vt_slow and percent is in (0, 100]; "
            "null selects a quad phase; ECC defaults to 50 rounds with "
            "diff_sizing_coefficients and a shared 1% budget per round"
        ),
    ),
    config_param(
        "place.timing_action_gradient_mode",
        "dreamplace",
        ("timing_action_gradient_mode",),
        "lut_action",
        type="str",
        choices=("off", "lut_action"),
        applies="placement,diff_opt,diff_sizing",
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
