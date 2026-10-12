"""Controls for the standalone discrete candidate buffering step."""

from .common import config_param
from .dreamplace_sizing import DEFAULT_DIFF_SIZING_COEFFICIENTS

SCHEMAS = (
    config_param(
        "place.diff_buffering_rounds",
        "dreamplace",
        ("diff_buffering_rounds",),
        10,
        range=(1, 1000),
        applies="diff_buffering",
        description="maximum discrete candidate buffering rounds after placement",
    ),
    config_param(
        "place.diff_buffering_selection_fraction",
        "dreamplace",
        ("diff_buffering_selection_fraction",),
        0.003,
        range=(0, 1),
        applies="diff_buffering",
        description="candidate-bearing net fraction selected per buffering round; must be positive",
    ),
    config_param(
        "place.diff_buffering_coefficients",
        "dreamplace",
        ("diff_buffering_coefficients",),
        DEFAULT_DIFF_SIZING_COEFFICIENTS,
        applies="diff_buffering",
        description="standalone buffering WNS/TNS/cap/slew coefficients with outer timing weight 1",
    ),
    config_param(
        "place.buffering_candidate_strategy",
        "dreamplace",
        ("buffering_candidate_strategy",),
        "continuous",
        applies="placement",
        choices=("continuous", "discrete_net_gradient"),
        description="candidate buffering action selector used by joint placement",
    ),
    config_param(
        "place.buffering_candidate_drive_type_mode",
        "dreamplace",
        ("buffering_candidate_drive_type_mode",),
        "single_fixed",
        applies="placement",
        choices=("single_fixed", "four_strength_table"),
        description="candidate buffering drive type representation",
    ),
    config_param(
        "place.buffering_candidate_drive_strength_table",
        "dreamplace",
        ("buffering_candidate_drive_strength_table",),
        "",
        applies="placement",
        description="external four-strength candidate buffer table",
    ),
)
