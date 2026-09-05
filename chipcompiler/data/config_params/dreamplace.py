from .common import config_param

DREAMPLACE_PARAMETER_DESCRIPTIONS = {
    "RePlAce_LOWER_PCOF": "lower bound ratio used in RePlAce for updating density weight",
    "RePlAce_UPPER_PCOF": "upper bound ratio used in RePlAce for updating density weight",
    "RePlAce_ref_hpwl": "reference HPWL used in RePlAce for updating density weight",
    "RePlAce_skip_energy_flag": (
        "whether skip density energy computation for fast mode, may not work with some solvers"
    ),
    "adjust_nctugr_area_flag": ("whether use ECC/iRT EGR congestion map to guide area adjustment"),
    "adjust_pin_area_flag": "whether use pin utilization map to guide area adjustment",
    "adjust_rudy_area_flag": "whether use RUDY/RISA map to guide area adjustment",
    "area_adjust_stop_ratio": "area_adjust_stop_ratio",
    "auto_adjust_bins": (
        "automatically derive num_bins_x and num_bins_y from the number of physical nodes"
    ),
    "bndry_padding_x": "horizontal padding around the edges of the floorplan",
    "bndry_padding_y": "vertical padding around the edges of the floorplan",
    "density_weight": "initial weight of density cost",
    "detailed_place_command": "commands for external detailed placement engine",
    "detailed_place_engine": "external detailed placement engine to be called after placement",
    "detailed_place_flag": "whether use internal detailed placement",
    "deterministic_flag": "whether require run-to-run determinism, may have efficiency overhead",
    "differentiable_timing_obj": (
        "compatibility flag for differentiable timing objective configuration"
    ),
    "dtype": "data type, float32 | float64",
    "dump_global_place_solution_flag": (
        "whether dump intermediate global placement solution as a compressed pickle object"
    ),
    "dump_legalize_solution_flag": (
        "whether dump intermediate legalization solution as a compressed pickle object"
    ),
    "enable_fillers": "enable filler cells",
    "enable_net_weighting": "enable timing-aware net weighting during global placement",
    "evaluate_pl": "evaluate .pl file without running anything (e.g., to get baseline PPA)",
    "gamma": (
        "base coefficient for log-sum-exp and weighted-average wirelength, a relative value "
        "to bin size"
    ),
    "get_congestion_map": "compute congestion map after placement complete",
    "global_place_flag": "whether use global placement",
    "global_place_stages": (
        "global placement configurations of each stage, a dictionary of "
        '{"num_bins_x", "num_bins_y", "iteration", "learning_rate", '
        '"learning_rate_decay", "wirelength", "optimizer", '
        '"Llambda_density_weight_iteration", "Lsub_iteration"}'
    ),
    "gp_noise_ratio": "noise to initial positions for global placement",
    "gpu": "enable gpu or not",
    "gpu_id": "which gpu to use",
    "ignore_net_degree": "ignore net degree larger than some value",
    "ignore_net_weight": "ignore net weight larger than some value for weight_hpwl reporting",
    "init_loc_perc_x": (
        "initial horizontal location of cells for global placement (% of layout width)"
    ),
    "init_loc_perc_y": (
        "initial vertical location of cells for global placement (% of layout height)"
    ),
    "legalize_flag": "whether use internal legalization",
    "macro_halo_x": "horizontal halo around movable macros",
    "macro_halo_y": "vertical halo around movable macros",
    "macro_overlap_flag": "whether enable MFP macro overlap",
    "macro_overlap_mult_weight": "weight multiplier for MFP macro overlap",
    "macro_overlap_weight": "initial weight of macro overlap cost",
    "macro_pin_halo_x": "horizontal halo applied to macro pins for pin-aware macro shaping",
    "macro_pin_halo_y": "vertical halo applied to macro pins for pin-aware macro shaping",
    "macro_place_flag": "whether enable two-stage macro placement",
    "max_net_weight": (
        'maximum net weight for timing optimization; negative values or "inf" mean no limit'
    ),
    "max_num_area_adjust": "maximum times to adjust node area",
    "max_pin_opt_adjust_rate": "max_pin_opt_adjust_rate",
    "max_route_opt_adjust_rate": "max_route_opt_adjust_rate",
    "momentum_decay_factor": "momentum decay factor used in timing-aware net-weight updates",
    "net_weighting_scheme": (
        "net-weighting scheme for timing-aware optimization, e.g. adam | lilith"
    ),
    "node_area_adjust_overflow": "the overflow where to adjust node area",
    "num_bins_x": "number of bins in horizontal direction",
    "num_bins_y": "number of bins in vertical direction",
    "num_threads": "number of CPU threads",
    "pin2pin_accumulate_weight": "increment added when accumulating an extra critical path",
    "pin2pin_max_weight": "maximum pin-to-pin timing weight",
    "pin2pin_min_weight": "minimum pin-to-pin timing weight",
    "pin2pin_net_weighting": "enable pin-to-pin net weighting for timing optimization",
    "pin2pin_weight": "base multiplier for pin-to-pin net weights",
    "pin_area_adjust_stop_ratio": "pin_area_adjust_stop_ratio",
    "pin_density": "target pin density for cells inflation",
    "pin_stretch_ratio": "pin_stretch_ratio",
    "plot_flag": "whether plot solution or not",
    "random_center_init_flag": "whether perform random initialization for global placement",
    "random_seed": "random seed",
    "risa_weights": "whether use weighted smooth HPWL with RISA net weights",
    "route_area_adjust_stop_ratio": "route_area_adjust_stop_ratio",
    "route_info_input": (
        "route information file (w. total H/V routing length & macro routing length contribution)"
    ),
    "route_num_bins_x": "number of routing grids/tiles",
    "route_num_bins_y": "number of routing grids/tiles",
    "route_opt_adjust_exponent": "exponent to adjust the routing utilization map",
    "scale_factor": "scale factor to avoid numerical overflow; 0.0 means not set",
    "shift_factor": (
        "shift factor to avoid numerical issues when the lower-left origin of rows is not (0, 0);"
    ),
    "sort_nets_by_degree": "whether sort nets by degree or not",
    "start_iter": "iteration to start pin-to-pin timing weighting",
    "timing_eval_flag": "enable timing evaluation reporting",
    "timing_opt_flag": (
        "legacy timing-driven global placement flag; enabling it raises an error because "
        "OpenTimer integration has been removed"
    ),
    "two_stage_density_scaler": "scale density weight after the macro placement stage",
    "unit_horizontal_capacity": "number of horizontal routing tracks per unit distance",
    "unit_pin_capacity": "number of pins per unit area",
    "unit_vertical_capacity": "number of vertical routing tracks per unit distance",
    "use_bb": "whether use the Barzilai-Borwein step size in Nesterov optimization",
    "with_sta": (
        "enable integrated STA initialization and differentiable timing updates during placement"
    ),
}


def _place(param: str, default: object, *, type: str | None = None):
    return config_param(
        f"place.{param}",
        "dreamplace",
        (param,),
        default,
        applies="placement",
        description=DREAMPLACE_PARAMETER_DESCRIPTIONS[param],
        type=type,
    )


SCHEMAS = (
    _place("RePlAce_LOWER_PCOF", 0.95),
    _place("RePlAce_UPPER_PCOF", 1.05),
    _place("RePlAce_ref_hpwl", 350000),
    _place("RePlAce_skip_energy_flag", 0),
    _place("adjust_nctugr_area_flag", 1),
    _place("adjust_pin_area_flag", 0),
    _place("adjust_rudy_area_flag", 0),
    _place("area_adjust_stop_ratio", 0.01),
    _place("auto_adjust_bins", 1),
    _place("bndry_padding_x", 0),
    _place("bndry_padding_y", 0),
    _place("density_weight", 0.00085),
    _place("detailed_place_command", ""),
    _place("detailed_place_engine", ""),
    _place("detailed_place_flag", 0),
    _place("deterministic_flag", 1),
    _place("differentiable_timing_obj", 0),
    _place("dtype", "float32"),
    _place("dump_global_place_solution_flag", 0),
    _place("dump_legalize_solution_flag", 0),
    _place("enable_fillers", 1),
    _place("enable_net_weighting", 0),
    _place("evaluate_pl", 0),
    _place("gamma", 4),
    _place("get_congestion_map", 1),
    _place("global_place_flag", 1),
    _place(
        "global_place_stages",
        [
            {
                "Llambda_density_weight_iteration": 1,
                "Lsub_iteration": 1,
                "iteration": 1000,
                "learning_rate": 1.0,
                "learning_rate_decay": 0.99,
                "num_bins_x": 32,
                "num_bins_y": 32,
                "optimizer": "nesterov",
                "wirelength": "weighted_average",
            }
        ],
        type="json",
    ),
    _place("gp_noise_ratio", 0.0),
    _place("gpu", 0),
    _place("gpu_id", 0),
    _place("ignore_net_degree", 100),
    _place("ignore_net_weight", 1),
    _place("init_loc_perc_x", 0.5),
    _place("init_loc_perc_y", 0.5),
    _place("legalize_flag", 1),
    _place("macro_halo_x", 0.0),
    _place("macro_halo_y", 0.0),
    _place("macro_overlap_flag", 0),
    _place("macro_overlap_mult_weight", 1.0),
    _place("macro_overlap_weight", 8e-06),
    _place("macro_pin_halo_x", 0.0),
    _place("macro_pin_halo_y", 0.0),
    _place("macro_place_flag", 0),
    _place("max_net_weight", "inf"),
    _place("max_num_area_adjust", 3),
    _place("max_pin_opt_adjust_rate", 1.5),
    _place("max_route_opt_adjust_rate", 2.0),
    _place("momentum_decay_factor", 0.5),
    _place("net_weighting_scheme", "lilith"),
    _place("node_area_adjust_overflow", 0.15),
    _place("num_bins_x", 32),
    _place("num_bins_y", 32),
    _place("num_threads", 8, type="int"),
    _place("pin2pin_accumulate_weight", 0.1),
    _place("pin2pin_max_weight", 1.0),
    _place("pin2pin_min_weight", 1.0),
    _place("pin2pin_net_weighting", 0),
    _place("pin2pin_weight", 2.5e-05),
    _place("pin_area_adjust_stop_ratio", 0.05),
    _place("pin_density", 0.6),
    _place("pin_stretch_ratio", 1.414213562),
    _place("plot_flag", 0),
    _place("random_center_init_flag", 1),
    _place("random_seed", 3000),
    _place("risa_weights", 0),
    _place("route_area_adjust_stop_ratio", 0.01),
    _place("route_info_input", "default"),
    _place("route_num_bins_x", 512),
    _place("route_num_bins_y", 512),
    _place("route_opt_adjust_exponent", 2.0),
    _place("scale_factor", 1.0),
    _place("shift_factor", [0.0, 0.0], type="list[float]"),
    _place("sort_nets_by_degree", 0),
    _place("start_iter", 0),
    _place("timing_eval_flag", 0),
    _place("timing_opt_flag", 0),
    _place("two_stage_density_scaler", 1000.0),
    _place("unit_horizontal_capacity", 1.5625),
    _place("unit_pin_capacity", 0.058),
    _place("unit_vertical_capacity", 1.45),
    _place("use_bb", 0),
    _place("with_sta", 0),
)
