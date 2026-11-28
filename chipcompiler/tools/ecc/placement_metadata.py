"""Load Liberty/SDC metadata for DreamPlace's Python timing operators."""

import logging

from chipcompiler.utility.path import path_text


def prepare_placement_metadata(module, inputs):
    """Prepare an ideal-clock placement graph without running native STA or RCX."""
    if any(inputs.get(key) for key in ("spef", "spef_path", "rcx_config")):
        raise ValueError("Python placement timing requires placement RC without SPEF/RCX")
    libs = [path_text(path) for path in inputs.get("lib_paths") or inputs.get("lib") or []]
    sdc = path_text(inputs.get("sdc_path") or inputs.get("sdc"))
    if not libs or not sdc:
        raise ValueError("Python placement timing requires Liberty files and an SDC path")
    if module._place_timing_active:
        module.destroy_place_timing()
    native = module.ecc
    if not hasattr(native, "load_placement_timing_metadata"):
        summary = dict(module.prepare_place_timing(dict(inputs)) or {})
        summary["timing_evaluator"] = "dreamplace_timing_propagation"
        summary["ecc_sta_run"] = False
        summary["placement_metadata_supported"] = False
        summary["parasitics_initialization"] = "python_placement_rc_pending"
        return summary
    if native.lib_init(lib_paths=libs) is not True or native.sdc_init(sdc) is not True:
        raise RuntimeError("placement timing metadata input initialization failed")
    config = module._place_timing_config(
        config=inputs.get("config") or inputs.get("sta_config") or "",
        work_dir=inputs.get("work_dir") or "",
        thread_number=int(inputs.get("thread_number", 2) or 2),
    )
    config_path = config.pop("config")
    try:
        if (
            native.load_placement_timing_metadata(config=config_path, config_dict=config)
            is not True
        ):
            raise RuntimeError("placement timing metadata preparation failed")
    except Exception:
        native.destroy_sta()
        raise
    if not native.is_placement_metadata_ready():
        # The loaded SDC is richer than the single-ideal-clock metadata model
        # (extra clocks, path exceptions, clock groups, or driving cells).
        # Fall back to the full native constraint export so the repair path
        # sees every constraint instead of a single global deadline.
        reason = native.placement_metadata_reason()
        logging.info(
            "placement metadata unavailable (%s); falling back to full native "
            "constraint export for repair timing",
            reason,
        )
        native.destroy_sta()
        summary = dict(module.prepare_place_timing(dict(inputs)) or {})
        summary["placement_metadata_supported"] = False
        summary["placement_metadata_reason"] = reason
        return summary
    module._place_timing_active = True
    module._place_timing_inputs = dict(inputs)
    return {
        "status": "ok",
        "mode": "placement_metadata_only",
        "timing_evaluator": "dreamplace_timing_propagation",
        "ecc_sta_run": False,
        "placement_metadata_supported": True,
        "parasitics_initialization": "python_placement_rc_pending",
        "lib_count": len(libs),
        "sdc_path": sdc,
    }
