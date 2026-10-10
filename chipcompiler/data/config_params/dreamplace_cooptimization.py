"""Public parameters for timing/routability placement and timing-optimization windows."""

from .common import config_param

SCHEMAS = (
    config_param(
        "place.stop_overflow",
        "dreamplace",
        ("stop_overflow",),
        0.1,
        applies="placement",
        description="stopping criteria, consider stop when the overflow reaches to a ratio",
    ),
    config_param(
        "place.timing_placement_carrier",
        "dreamplace",
        ("timing_placement_carrier",),
        "direct_loss",
        applies="placement",
        description=(
            "coordinate timing method; explicit direct_loss or pin2pin selects "
            "mutually exclusive GP controls; "
            "gradient_net_weight retains gradient projection"
        ),
    ),
    config_param(
        "place.timing_topology_refresh_interval",
        "dreamplace",
        ("timing_topology_refresh_interval",),
        15,
        applies="placement",
        description="GP steps between full timing topology refreshes",
    ),
    config_param(
        "place.timing_topology_enable_overflow_threshold",
        "dreamplace",
        ("timing_topology_enable_overflow_threshold",),
        0.35,
        applies="placement",
        description="density overflow below which timing topology updates activate",
    ),
    config_param(
        "place.timing_objective_lane",
        "dreamplace",
        ("timing_objective_lane",),
        "timing_only",
        applies="placement",
        description="timing objective terms, timing_only | timing_slew_cap",
    ),
    config_param(
        "place.timing_grad_balance_target_ratio",
        "dreamplace",
        ("timing_grad_balance_target_ratio",),
        0.2,
        applies="placement",
        description=(
            "initial target ratio between weighted timing-gradient and wirelength-gradient "
            "L1 norms in direct-loss placement; 0 disables automatic balancing"
        ),
    ),
    config_param(
        "place.timing_aggregation_mode",
        "dreamplace",
        ("timing_aggregation_mode",),
        "hard",
        applies="placement",
        choices=("hard", "smooth"),
        description=(
            "AAT/RAT aggregation: hard max/min or smooth LSE; "
            "endpoint WNS/TNS retain hard reductions"
        ),
    ),
    config_param(
        "place.timing_aggregation_tau_ps",
        "dreamplace",
        ("timing_aggregation_tau_ps",),
        2.0,
        applies="placement",
        description=(
            "positive LSE temperature in ps for smooth AAT/RAT aggregation; "
            "smaller values approach hard max/min"
        ),
    ),
    config_param(
        "place.placement_sizing_mode",
        "dreamplace",
        ("placement_sizing_mode",),
        "place_only",
        applies="placement",
        description="placement optimization lane, place_only | size_only | joint",
    ),
    config_param(
        "place.openroad_vt_suffixes",
        "dreamplace",
        ("openroad_vt_suffixes",),
        ["H7H", "H7R", "H7L"],
        applies="placement",
        description="OpenROAD VT suffixes used to classify equivalent Liberty cells",
    ),
    config_param(
        "place.routability_opt_flag",
        "dreamplace",
        ("routability_opt_flag",),
        1,
        applies="placement",
        description="whether enable routability optimization",
    ),
    config_param(
        "place.l_shape_routability_flag",
        "dreamplace",
        ("l_shape_routability_flag",),
        1,
        applies="placement",
        description="whether enable L-shape routability optimization",
    ),
    config_param(
        "place.l_direction_use_gpugr",
        "dreamplace",
        ("l_direction_use_gpugr",),
        0,
        applies="placement",
        description=(
            "whether use Xplace gpugr route entries instead of iRT EGR guide to resolve "
            "L directions"
        ),
    ),
    config_param(
        "place.l_shape_use_ggr_topology",
        "dreamplace",
        ("l_shape_use_ggr_topology",),
        0,
        applies="placement",
        description=(
            "whether use GGR-exported L-shape topology pack instead of diff-side FLUTE "
            "refresh for L-shape routability"
        ),
    ),
    config_param(
        "place.l_shape_capacity_al_enable",
        "dreamplace",
        ("l_shape_capacity_al_enable",),
        0,
        applies="placement",
        description=(
            "whether use per-routing-bin AL multiplier memory as the hard-GGR L-shape "
            "capacity-pressure source"
        ),
    ),
    config_param(
        "place.l_shape_overflow_threshold",
        "dreamplace",
        ("l_shape_overflow_threshold",),
        0.3,
        applies="placement",
        description=(
            "placement overflow threshold below which disabled L-shape diff/routability "
            "force is allowed to start or re-enable"
        ),
    ),
    config_param(
        "place.adjust_gpugr_area_flag",
        "dreamplace",
        ("adjust_gpugr_area_flag",),
        1,
        applies="placement",
        description="whether use Xplace gpugr overflow map to guide area adjustment",
    ),
    config_param(
        "place.enhanced_inflation_flag",
        "dreamplace",
        ("enhanced_inflation_flag",),
        0,
        applies="placement",
        description="whether enable the enhanced outer-loop inflation controller skeleton",
    ),
    config_param(
        "place.enhanced_inflation_replay_best_round_flag",
        "dreamplace",
        ("enhanced_inflation_replay_best_round_flag",),
        0,
        applies="placement",
        description=(
            "whether replay the best recorded enhanced inflation round after rolling "
            "back inflated geometry"
        ),
    ),
    config_param(
        "place.legalize_before_each_inflation_flag",
        "dreamplace",
        ("legalize_before_each_inflation_flag",),
        0,
        applies="placement",
        description=(
            "whether each ordinary inflation round waits for stop_overflow, legalizes "
            "physical cell geometry, runs congestion estimation, and then reapplies "
            "cumulative inflation before area adjustment"
        ),
    ),
    config_param(
        "place.gpugr_backend",
        "dreamplace",
        ("gpugr_backend",),
        "auto",
        applies="placement",
        description=(
            "GGR backend selection: auto chooses cuda when available and cpu_pr_mt "
            "otherwise; cuda requires a CUDA-capable gpugr build; cpu_pr is explicit "
            "serial diagnostic pattern routing; cpu_pr_mt is deterministic parallel CPU "
            "pattern routing and uses num_threads as its requested worker count; all CPU "
            "pattern backends require rrrIters=0"
        ),
    ),
    config_param(
        "place.gpugr_bottom_routing_layer",
        "dreamplace",
        ("gpugr_bottom_routing_layer",),
        "",
        applies="placement",
        description=(
            "inclusive bottom routing-layer name passed to GPUGR; empty uses the first "
            "LEF routing layer"
        ),
    ),
    config_param(
        "place.gpugr_top_routing_layer",
        "dreamplace",
        ("gpugr_top_routing_layer",),
        "",
        applies="placement",
        description=(
            "inclusive top routing-layer name passed to GPUGR; empty uses the last LEF "
            "routing layer"
        ),
    ),
    config_param(
        "place.gpugr_area_adjust_congestion_mode",
        "dreamplace",
        ("gpugr_area_adjust_congestion_mode",),
        "max_hv",
        applies="placement",
        description=(
            "congestion signal used by GPUGR area inflation: union, direction-sensitive "
            "max_hv, or direction-sensitive max_hv_effective using routed wire plus via "
            "demand over nominal capacity minus fixed and movable obstacle usage"
        ),
    ),
    config_param(
        "place.gpugr_final_eval_flag",
        "dreamplace",
        ("gpugr_final_eval_flag",),
        0,
        applies="placement",
        description=(
            "whether run a final gpugr evaluation after placement finishes, similar to "
            "Xplace final_route_eval"
        ),
    ),
    config_param(
        "place.gpugr_final_eval_rrr_iters",
        "dreamplace",
        ("gpugr_final_eval_rrr_iters",),
        1,
        applies="placement",
        description="rrrIters passed to gpugr final evaluation",
    ),
    config_param(
        "place.timing_opt_enabled",
        "dreamplace",
        ("timing_opt_enabled",),
        1,
        applies="placement",
        description="run the electrical timing-optimization windows during placement",
    ),
    config_param(
        "place.timing_opt_buffering_enabled",
        "dreamplace",
        ("timing_opt_buffering_enabled",),
        0,
        applies="placement",
        description="enable segment buffering in electrical timing-optimization windows",
    ),
    config_param(
        "place.timing_opt_max_windows",
        "dreamplace",
        ("timing_opt_max_windows",),
        5,
        applies="placement",
        description="maximum timing-optimization windows in one placement run, up to five",
    ),
    config_param(
        "place.timing_opt_overflow_milestones",
        "dreamplace",
        ("timing_opt_overflow_milestones",),
        [],
        type="list[float]",
        applies="placement",
        description=(
            "descending one-shot overflow thresholds for timing-optimization windows; "
            "empty uses inflation-triggered windows"
        ),
    ),
    config_param(
        "place.timing_opt_sizing_rounds",
        "dreamplace",
        ("timing_opt_sizing_rounds",),
        10,
        applies="placement",
        description="maximum discrete size/VT rounds in each timing-optimization window, up to ten",
    ),
    config_param(
        "place.timing_coeff_growth_factor",
        "dreamplace",
        ("timing_coeff_growth_factor",),
        1.01,
        applies="placement",
        description=(
            "positive finite multiplier applied to WNS/TNS coefficients at each GP "
            "density-weight update; 1 disables growth; size_only skips this schedule"
        ),
    ),
    config_param(
        "place.timing_opt_coefficients",
        "dreamplace",
        ("timing_opt_coefficients",),
        {"mode": "inherit"},
        applies="placement",
        description=(
            "GP sizing-window coefficient policy: mode=inherit uses live placement values; "
            "mode=fixed requires wns, tns, slew and cap during S rounds only, "
            "with outer timing weight 1; placement weights are restored on exit"
        ),
    ),
    # Compatibility aliases for existing 13-case profiles and workspace
    # configs.  Aliases write the canonical timing_opt_* fields directly.
    config_param(
        "place.inflation_s5b1_enabled",
        "dreamplace",
        ("timing_opt_enabled",),
        1,
        applies="placement",
        description="Deprecated alias for place.timing_opt_enabled",
    ),
    config_param(
        "place.inflation_s5b1_buffering_enabled",
        "dreamplace",
        ("timing_opt_buffering_enabled",),
        0,
        applies="placement",
        description="Deprecated alias for place.timing_opt_buffering_enabled",
    ),
    config_param(
        "place.inflation_s5b1_max_windows",
        "dreamplace",
        ("timing_opt_max_windows",),
        5,
        applies="placement",
        description="Deprecated alias for place.timing_opt_max_windows",
    ),
    config_param(
        "place.inflation_s5b1_overflow_milestones",
        "dreamplace",
        ("timing_opt_overflow_milestones",),
        [],
        type="list[float]",
        applies="placement",
        description="Deprecated alias for place.timing_opt_overflow_milestones",
    ),
    config_param(
        "place.inflation_sizing_rounds",
        "dreamplace",
        ("timing_opt_sizing_rounds",),
        10,
        applies="placement",
        description="Deprecated alias for place.timing_opt_sizing_rounds",
    ),
    config_param(
        "place.discrete_gradient_topk_shared_budget_percent",
        "dreamplace",
        ("discrete_gradient_topk_shared_budget_percent",),
        1.0,
        applies="placement",
        description="percentage of sizeable cells sharing one size/VT action budget",
    ),
    config_param(
        "place.buffering_mode",
        "dreamplace",
        ("buffering_mode",),
        "segment",
        applies="placement",
        description="buffering representation, segment | candidate",
    ),
    config_param(
        "place.buffering_segment_strategy",
        "dreamplace",
        ("buffering_segment_strategy",),
        "continuous",
        applies="placement",
        description="segment count optimization strategy, continuous | discrete_net_gradient",
    ),
    config_param(
        "place.buffering_segment_count_z_init",
        "dreamplace",
        ("buffering_segment_count_z_init",),
        0.1,
        applies="placement",
        description="initial relaxed repeater count on each segment",
    ),
    config_param(
        "place.buffering_fixed_bsu_index",
        "dreamplace",
        ("buffering_fixed_bsu_index",),
        None,
        applies="placement",
        description="optional fixed buffer index resolved from the legal buffer table",
        type="int",
    ),
    config_param(
        "place.buffering_max_repeaters_per_segment",
        "dreamplace",
        ("buffering_max_repeaters_per_segment",),
        3,
        applies="placement",
        description="maximum accepted repeaters on one segment",
    ),
    config_param(
        "place.buffering_route_b_selection_fraction",
        "dreamplace",
        ("buffering_route_b_selection_fraction",),
        0.001,
        applies="placement",
        description="fraction of segment candidates selected in one discrete buffering batch",
    ),
    config_param(
        "place.buffering_segment_transfer_backend",
        "dreamplace",
        ("buffering_segment_transfer_backend",),
        "segment_transfer_native",
        applies="placement",
        description="native segment timing transfer implementation",
    ),
    config_param(
        "place.buffering_segment_live_geometry",
        "dreamplace",
        ("buffering_segment_live_geometry",),
        1,
        applies="placement",
        description="update buffered segment timing from current placement geometry",
    ),
    config_param(
        "place.buffering_segment_integer_projection_interval",
        "dreamplace",
        ("buffering_segment_integer_projection_interval",),
        0,
        applies="placement",
        description=(
            "GP steps between integer buffer projection calls; 0 disables periodic projection"
        ),
    ),
    config_param(
        "place.buffering_segment_integer_projection_start_step",
        "dreamplace",
        ("buffering_segment_integer_projection_start_step",),
        0,
        applies="placement",
        description="first GP step eligible for periodic buffer projection",
    ),
    config_param(
        "place.buffering_segment_integer_projection_project_bsu",
        "dreamplace",
        ("buffering_segment_integer_projection_project_bsu",),
        0,
        applies="placement",
        description="project buffer master indices together with integer repeater counts",
    ),
    config_param(
        "place.buffering_discrete_count_proximal_lambda",
        "dreamplace",
        ("buffering_discrete_count_proximal_lambda",),
        0.0,
        applies="placement",
        description="proximal penalty coefficient for discrete repeater count changes",
    ),
    config_param(
        "place.relaxed_buffer_timing_integration_mode",
        "dreamplace",
        ("relaxed_buffer_timing_integration_mode",),
        "dynamic_net_provider",
        applies="placement",
        description="virtual buffer timing integration provider",
    ),
    config_param(
        "place.joint_segment_virtual_density_enabled",
        "dreamplace",
        ("joint_segment_virtual_density_enabled",),
        0,
        applies="placement",
        description="include persistent virtual buffer footprints in placement density",
    ),
    config_param(
        "place.buffering_segment_projection_min_z_to_insert",
        "dreamplace",
        ("buffering_segment_projection_min_z_to_insert",),
        0.5,
        applies="placement",
        description="minimum relaxed repeater count eligible for physical insertion",
    ),
    config_param(
        "place.buffering_continuous_relaxed_optimization",
        "dreamplace",
        ("buffering_continuous_relaxed_optimization",),
        default=False,
        applies="placement",
        description="enable continuous relaxed buffer optimization",
    ),
    config_param(
        "place.buffering_segment_count_tns_gradient",
        "dreamplace",
        ("buffering_segment_count_tns_gradient",),
        default=False,
        applies="placement",
        description="enable TNS gradients with respect to segment repeater counts",
    ),
    config_param(
        "place.timing_obj_profile",
        "dreamplace",
        ("timing_obj_profile",),
        0,
        applies="placement",
        description="enable timing objective performance counters",
    ),
    config_param(
        "place.timing_obj_profile_interval",
        "dreamplace",
        ("timing_obj_profile_interval",),
        100,
        applies="placement",
        description="steps between timing objective performance summaries",
    ),
    config_param(
        "place.l_shape_grad_target_ratio",
        "dreamplace",
        ("l_shape_grad_target_ratio",),
        0.2,
        applies="placement",
        description=(
            "target ratio between weighted preconditioned L-shape gradient norm and "
            "preconditioned base wirelength+density gradient norm"
        ),
    ),
    config_param(
        "place.l_shape_grad_target_ratio_max",
        "dreamplace",
        ("l_shape_grad_target_ratio_max",),
        0.2,
        applies="placement",
        description="maximum adaptive routability gradient target ratio",
    ),
    config_param(
        "place.l_shape_update_interval",
        "dreamplace",
        ("l_shape_update_interval",),
        30,
        applies="placement",
        description=(
            "number of global-placement iterations between L-shape topology and direction refreshes"
        ),
    ),
)
