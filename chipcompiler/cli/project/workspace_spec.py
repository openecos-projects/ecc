"""Project configuration to Engine Workspace Spec projection."""

from copy import deepcopy

from chipcompiler.cli.project.config import resolve_pdk_root
from chipcompiler.cli.project.design_inputs import resolve_design_inputs
from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory


def workspace_update_spec(workspace_path: str, cfg, flow_config: dict | None):
    snapshot = read_engineering_snapshot_from_directory(workspace_path)
    spec = deepcopy(snapshot["workspaceSpec"])
    bindings = deepcopy(snapshot["workspaceBindings"])
    # A Project refresh owns structural settings only. Existing Workspace
    # parameters are merged and marked as preserved by update_workspace_from_spec;
    # carrying the Snapshot's resolved defaults here would incorrectly turn
    # every one of them into an explicit request for the new flow.
    spec["parameters"] = {}
    spec["design"] = {
        "name": cfg.design_name,
        "topModule": cfg.design_top,
        "clockPort": cfg.design_clock_port,
    }
    inputs = resolve_design_inputs(cfg)
    input_specs = []
    input_bindings = {}

    def add(role: str, path: str, index: int | None = None) -> None:
        if not path:
            return
        input_id = role if index is None else f"{role}-{index}"
        input_specs.append({"inputId": input_id, "role": role})
        input_bindings[input_id] = path

    from chipcompiler.cli.project.effective_config import _entry_step_for_target
    from chipcompiler.rtl2gds import normalize_flow_step

    entry_step = _entry_step_for_target(cfg, flow_config)
    rtl_mode = normalize_flow_step(entry_step or "") == "Synthesis"
    if rtl_mode:
        for index, path in enumerate(inputs.rtl):
            add("rtl", path, index)
    else:
        add("netlist", inputs.netlist)
    add("def", inputs.def_)
    add("goldenNetlist", inputs.golden_netlist)
    add("sdc", inputs.sdc)
    add("spef", inputs.spef)
    spec["inputMode"] = "rtl" if rtl_mode else "postSynthesis"
    spec["inputs"] = input_specs
    bindings["inputs"] = input_bindings

    current_pdk = spec.get("pdk") if isinstance(spec.get("pdk"), dict) else {}
    spec["pdk"] = {
        "familyId": cfg.pdk_name,
        "mode": "default",
        **(
            {"version": current_pdk["version"]}
            if cfg.pdk_name == current_pdk.get("familyId") and current_pdk.get("version")
            else {}
        ),
    }
    bindings["pdk"] = {
        "root": resolve_pdk_root(cfg),
        **({"version": current_pdk["version"]} if current_pdk.get("version") else {}),
    }
    flow = {"flowId": cfg.flow_preset}
    if isinstance(flow_config, dict) and flow_config.get("start_step"):
        flow["fromStepId"] = flow_config["start_step"]
        flow["throughStepId"] = flow_config.get("end_step") or flow_config["start_step"]
    spec["flow"] = flow
    return spec, bindings
