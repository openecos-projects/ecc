"""DreamPlace run modes and the config each geometry-only mode forces.

Macro placement and legalization run DreamPlace as a plain, timing-free
placer whatever the baseline enables. The forced settings are written into
the step's own config file (:func:`force_mode_config`) so the file is the
effective configuration, and the module applies them again at run time.
"""

from enum import Enum
from typing import Final

from chipcompiler.data import SkippableStepEnum, StepEnum


class DreamplaceRunMode(Enum):
    PLACEMENT = "placement"
    DIFF_OPT = "diff_opt"
    DIFF_SIZING = "diff_sizing"
    MACRO_PLACEMENT = "macro_placement"
    LEGALIZATION = "legalization"


#: Timing-free placement settings of every mode other than the placement lanes.
GEOMETRY_ONLY_CONFIG: Final = {
    "place_io_engine": "ecc",
    "flow_kind": "placement",
    "placement_sizing_mode": "place_only",
    "sizing_parameterization": "logits",
    "diff_timing_driven_placement": 0,
    "differentiable_timing_obj": 0,
    "with_sta": 0,
    "timing_rc_mode": "placement",
    "timing_opt_flag": 0,
    "timing_eval_flag": 0,
    "enable_net_weighting": 0,
    "pin2pin_net_weighting": 0,
    "timing_opt_enabled": 0,
    "inflation_s5b1_enabled": 0,
    "repair_buffering_enable": False,
    "repair_buffering_midplace_enable": False,
    "macro_exclusion_field_flag": 0,
    "d_metric_legalize_flag": 0,
    "routability_opt_flag": 0,
    "l_shape_routability_flag": 0,
    "adjust_gpugr_area_flag": 0,
    "gpugr_final_eval_flag": 0,
    "buffering_continuous_relaxed_optimization": False,
    "buffering_segment_count_tns_gradient": False,
    "buffering_segment_strategy": "continuous",
    "buffering_candidate_strategy": "continuous",
    "joint_segment_virtual_density_enabled": 0,
}

#: Placer stages each geometry-only mode runs; set after the flow defaults.
MODE_FLAGS: Final = {
    DreamplaceRunMode.MACRO_PLACEMENT: {
        "macro_only": 1,
        "detailed_place_flag": 0,
        "global_place_flag": 1,
        "macro_place_flag": 1,
        "legalize_flag": 1,
        "two_stage_flag": 0,
        "macro_halo_x": 2000,
        "macro_halo_y": 2000,
        "routability_opt_flag": 0,
        "get_congestion_map": 0,
        "egr_padding_flag": 0,
    },
    DreamplaceRunMode.LEGALIZATION: {
        "macro_only": 0,
        "global_place_flag": 0,
        "legalize_flag": 1,
        # Geometry-only legalization preserves the repaired hold timing.
        "detailed_place_flag": 0,
        "enable_fillers": 0,
        "random_center_init_flag": 0,
        "auto_adjust_bins": 1,
        "post_legalization_adaptive_padding_flag": 0,
    },
}

# Steps whose DreamPlace config runs a geometry-only mode; timing_optimization
# owns an inner legalization.
_STEP_MODES: Final = {
    StepEnum.MACRO_PLACEMENT.value: DreamplaceRunMode.MACRO_PLACEMENT,
    StepEnum.LEGALIZATION.value: DreamplaceRunMode.LEGALIZATION,
    SkippableStepEnum.TIMING_OPT.value: DreamplaceRunMode.LEGALIZATION,
}


def step_geometry_mode(step_name: str) -> DreamplaceRunMode | None:
    """The geometry-only mode *step_name*'s DreamPlace config runs, if any."""
    return _STEP_MODES.get(str(step_name))


def force_mode_config(config: dict, mode: DreamplaceRunMode) -> dict:
    """*config* with the settings a geometry-only *mode* forces; others unchanged."""
    flags = MODE_FLAGS.get(mode)
    if flags is None:
        return config
    return {**config, **GEOMETRY_ONLY_CONFIG, **flags}
