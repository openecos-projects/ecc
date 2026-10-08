# The descriptions below are a vendored mirror of the upstream DreamPlace
# template metadata (chipcompiler/thirdparty/ecc-dreamplace/dreamplace/params.json,
# excluded from the wheel). They are copied rather than derived at runtime
# because deployed packages do not ship the thirdparty tree;
# test_descriptions.match_upstream_metadata fails the build when the copy
# drifts from the canonical template.
from .common import config_param

DREAMPLACE_PARAMETER_DESCRIPTIONS = {
    "RePlAce_LOWER_PCOF": "lower bound ratio used in RePlAce for updating density weight",
    "RePlAce_UPPER_PCOF": "upper bound ratio used in RePlAce for updating density weight",
    "RePlAce_ref_hpwl": "reference HPWL used in RePlAce for updating density weight",
    "RePlAce_skip_energy_flag": (
        "whether skip density energy computation for fast mode, may not work with some solvers"
    ),
    "adjust_gpugr_area_flag": "whether use Xplace gpugr overflow map to guide area adjustment",
    "adjust_nctugr_area_flag": (
        "legacy compatibility key; when enabled use the ECC/iRT EGR congestion map for area "
        "adjustment (NCTUgr is not invoked)"
    ),
    "adjust_pin_area_flag": "whether use pin utilization map to guide area adjustment",
    "adjust_rudy_area_flag": "whether use RUDY/RISA map to guide area adjustment",
    "area_adjust_stop_ratio": "area_adjust_stop_ratio",
    "auto_adjust_bins": (
        "automatically derive num_bins_x and num_bins_y from the number of physical nodes"
    ),
    "bndry_padding_x": "horizontal padding around the edges of the floorplan",
    "bndry_padding_y": "vertical padding around the edges of the floorplan",
    "buffering_continuous_steps": "number of steps in the standalone buffering optimizer",
    "buffering_fixed_buffer_master": "physical buffer master used for Segment buffering",
    "buffering_segment_count_timing_backend": "timing implementation for Segment buffering",
    "density_weight": "initial weight of density cost",
    "cell_model_schema": "cell timing model schema; null uses the existing flow default",
    "piecewise_gradient_mode": "piecewise cell gradient, linear6_ste | native_piecewise",
    "timing_rc_mode": "timing parasitics, placement | gr; gr requires native ECC CPU sizing or STA",
    "detailed_place_command": "commands for external detailed placement engine",
    "detailed_place_engine": "external detailed placement engine to be called after placement",
    "detailed_place_flag": "whether use internal detailed placement",
    "deterministic_flag": "whether require run-to-run determinism, may have efficiency overhead",
    "discrete_gradient_topk_up_percent": "cell percentage eligible for discrete upsizing",
    "discrete_gradient_topk_vt_percent": "cell percentage eligible for discrete VT changes",
    "joint_buffer_commit_period": "optimizer step interval between joint physical commit requests",
    "joint_buffer_outer_iterations": "maximum joint optimizer windows separated by native refresh",
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
    "flow_kind": "optimization profile executed inside the placement step",
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
    "gpugr_backend": (
        "GGR backend selection: auto chooses cuda when available and cpu_pr_mt otherwise; "
        "cuda requires a CUDA-capable gpugr build; cpu_pr is explicit serial diagnostic pattern "
        "routing; cpu_pr_mt is deterministic parallel CPU pattern routing and uses num_threads "
        "as its requested worker count; all CPU pattern backends require rrrIters=0"
    ),
    "gpugr_area_adjust_rrr_iters": (
        "rrrIters passed to gpugr when adjust_gpugr_area_flag is enabled"
    ),
    "gpugr_area_adjust_congestion_mode": (
        "congestion signal used by GPUGR area inflation: union, direction-sensitive max_hv, "
        "or direction-sensitive max_hv_effective using routed wire plus via demand over "
        "nominal capacity minus fixed and movable obstacle usage"
    ),
    "ignore_net_degree": "ignore net degree larger than some value",
    "ignore_net_weight": "ignore net weight larger than some value for weight_hpwl reporting",
    "init_loc_perc_x": (
        "initial horizontal location of cells for global placement (% of layout width)"
    ),
    "init_loc_perc_y": (
        "initial vertical location of cells for global placement (% of layout height)"
    ),
    "inflation_min_interval": (
        "minimum completed GP steps between applied inflation rounds; 0 disables the interval guard"
    ),
    "l_shape_gradient_mode": (
        "routing gradient mode: translation preserves fixed-size field guidance; "
        "full differentiates the fixed-epoch electric energy through positions and "
        "segment dimensions (hard L, electric only)"
    ),
    "joint_quality_profile": "optional canonical profile for joint optimization",
    "legalize_flag": "whether use internal legalization",
    "l_shape_routability_flag": "whether enable L-shape routability optimization",
    "l_shape_update_interval": (
        "number of global-placement iterations between L-shape topology and direction refreshes"
    ),
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
    "place_io_engine": "physical database backend used by DREAMPlace",
    "placement_initial_learning_rate_max": (
        "optional cap for the estimated initial placement learning rate"
    ),
    "random_center_init_flag": "whether perform random initialization for global placement",
    "random_seed": "random seed",
    "risa_weights": "whether use weighted smooth HPWL with RISA net weights",
    "real_size_execution_mode": ("real-size execution mode, continuous_only | warmup_to_discrete"),
    "real_size_warmup_steps": (
        "number of real-size Adam steps before a warmup-to-discrete transition"
    ),
    "route_area_adjust_stop_ratio": "route_area_adjust_stop_ratio",
    "route_info_input": (
        "route information file (w. total H/V routing length & macro routing length contribution)"
    ),
    "route_num_bins_x": "number of routing grids/tiles",
    "route_num_bins_y": "number of routing grids/tiles",
    "route_opt_adjust_exponent": "exponent to adjust the routing utilization map",
    "rc_tcl": "OpenROAD RC setup Tcl, resolved relative to the PDK root when relative",
    "scale_factor": "scale factor to avoid numerical overflow; 0.0 means not set",
    "shift_factor": (
        "shift factor to avoid numerical issues when the lower-left origin of rows is not (0, 0);"
    ),
    "sort_nets_by_degree": "whether sort nets by degree or not",
    "sizing_parameterization": "continuous sizing coordinate, logits | real_size",
    "start_iter": "iteration to start pin-to-pin timing weighting",
    "timing_eval_flag": "enable timing evaluation reporting",
    "timing_surrogate_mode": (
        "cell timing evaluation mode, auto | mixed | lut_only | surrogate_only"
    ),
    "diff_timing_driven_placement": "enable differentiable timing in the placement flow",
    "early_stop_restore_best": (
        "restore the best continuous sizing state at the end of optimization"
    ),
    "timing_opt_flag": (
        "legacy timing-driven global placement flag; enabling it raises an error because "
        "OpenTimer integration has been removed"
    ),
    "two_stage_density_scaler": "scale density weight after the macro placement stage",
    "unit_horizontal_capacity": "number of horizontal routing tracks per unit distance",
    "unit_pin_capacity": "number of pins per unit area",
    "unit_vertical_capacity": "number of vertical routing tracks per unit distance",
    "use_bb": "whether to use Barzilai-Borwein step-size updates in Nesterov optimization",
    "with_sta": (
        "enable integrated STA initialization and differentiable timing updates during placement"
    ),
}


def _place(
    param: str,
    default: object,
    *,
    type: str | None = None,
    choices: tuple[str, ...] | None = None,
):
    return config_param(
        f"place.{param}",
        "dreamplace",
        (param,),
        default,
        applies="placement",
        description=DREAMPLACE_PARAMETER_DESCRIPTIONS[param],
        type=type,
        choices=choices,
    )


SCHEMAS = (
    _place("RePlAce_LOWER_PCOF", 0.95),
    _place("RePlAce_UPPER_PCOF", 1.05),
    _place("RePlAce_ref_hpwl", 350000),
    _place("RePlAce_skip_energy_flag", 0),
    _place("adjust_nctugr_area_flag", 0),
    _place("adjust_pin_area_flag", 0),
    _place("adjust_rudy_area_flag", 0),
    _place("area_adjust_stop_ratio", 0.01),
    _place("auto_adjust_bins", 0),
    _place("bndry_padding_x", 0),
    _place("bndry_padding_y", 0),
    _place("buffering_continuous_steps", 120),
    _place("buffering_fixed_buffer_master", "BUFX1H7L"),
    _place("buffering_segment_count_timing_backend", "cpp_cuda_segment_transfer_explicit_autograd"),
    _place("density_weight", 0.00008),
    _place("cell_model_schema", "main_id_arc_offset_piecewise_linear", type="str"),
    _place(
        "piecewise_gradient_mode", "native_piecewise", choices=("linear6_ste", "native_piecewise")
    ),
    _place("timing_rc_mode", "placement", choices=("placement", "gr")),
    _place("detailed_place_command", ""),
    _place("detailed_place_engine", ""),
    _place("detailed_place_flag", 1),
    _place("deterministic_flag", 1),
    _place("discrete_gradient_topk_up_percent", 30.0),
    _place("discrete_gradient_topk_vt_percent", 10.0),
    _place("joint_buffer_commit_period", 100, type="int"),
    _place("joint_buffer_outer_iterations", 1, type="int"),
    _place("differentiable_timing_obj", 1),
    _place("early_stop_restore_best", 1),
    _place("dtype", "float32"),
    _place("dump_global_place_solution_flag", 0),
    _place("dump_legalize_solution_flag", 0),
    _place("enable_fillers", 0),
    _place("enable_net_weighting", 0),
    _place("evaluate_pl", 0),
    _place(
        "flow_kind",
        "placement",
        choices=("placement", "sta", "sizing", "buffering", "joint"),
    ),
    _place("gamma", 4),
    _place("get_congestion_map", 0),
    _place("global_place_flag", 1),
    _place(
        "global_place_stages",
        [
            {
                "Llambda_density_weight_iteration": 1,
                "Lsub_iteration": 1,
                "iteration": 3000,
                "learning_rate": 0.01,
                "learning_rate_decay": 1.0,
                "num_bins_x": 256,
                "num_bins_y": 256,
                "optimizer": "nesterov",
                "wirelength": "weighted_average",
            }
        ],
        type="json",
    ),
    _place("gp_noise_ratio", 0.0),
    _place("gpu", 0),
    _place("gpu_id", 0),
    _place("gpugr_area_adjust_rrr_iters", 0),
    _place("ignore_net_degree", 100),
    _place("ignore_net_weight", 1),
    _place("init_loc_perc_x", 0.5),
    _place("init_loc_perc_y", 0.5),
    _place("inflation_min_interval", 0, type="int"),
    _place("l_shape_gradient_mode", "translation", choices=("translation", "full")),
    _place(
        "joint_quality_profile",
        "",
        choices=(
            "",
            "proximal_alternating_v1",
            "staged_smoke_v1",
            "segment_count_direct_joint_v1",
        ),
    ),
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
    _place("num_bins_x", 256),
    _place("num_bins_y", 256),
    _place("num_threads", 8, type="int"),
    _place("pin2pin_accumulate_weight", 0.2),
    _place("pin2pin_max_weight", 50.0),
    _place("pin2pin_min_weight", 10.0),
    _place("pin2pin_net_weighting", 0),
    _place("pin2pin_weight", 0.0005),
    _place("pin_area_adjust_stop_ratio", 0.05),
    _place("pin_density", -1, type="float"),
    _place("pin_stretch_ratio", 1.414213562),
    _place("plot_flag", 1),
    _place("place_io_engine", "ecc", choices=("ieda", "ecc", "openroad")),
    _place("placement_initial_learning_rate_max", None, type="float"),
    _place("random_center_init_flag", 1),
    _place("random_seed", 3000),
    _place(
        "real_size_execution_mode",
        "continuous_only",
        choices=("continuous_only", "warmup_to_discrete"),
    ),
    _place("real_size_warmup_steps", 0),
    _place("risa_weights", 0),
    _place("route_area_adjust_stop_ratio", 0.01),
    _place("route_info_input", "default"),
    _place("route_num_bins_x", 512),
    _place("route_num_bins_y", 512),
    _place("route_opt_adjust_exponent", 2.0),
    _place("rc_tcl", ""),
    _place("scale_factor", 1.0),
    _place("shift_factor", [0.0, 0.0], type="list[float]"),
    _place("sizing_parameterization", "logits", choices=("logits", "real_size")),
    _place("sort_nets_by_degree", 0),
    _place("start_iter", 0),
    _place("timing_eval_flag", 1),
    _place(
        "timing_surrogate_mode",
        "auto",
        choices=("auto", "mixed", "lut_only", "surrogate_only"),
    ),
    _place("diff_timing_driven_placement", 1),
    _place("timing_opt_flag", 0),
    _place("two_stage_density_scaler", 1000.0),
    _place("unit_horizontal_capacity", 1.5625),
    _place("unit_pin_capacity", 0.058),
    _place("unit_vertical_capacity", 1.45),
    _place("use_bb", 0),
    _place("with_sta", 1),
)
