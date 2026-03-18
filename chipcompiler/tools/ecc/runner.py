#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os
       
from chipcompiler.data import WorkspaceStep, Workspace, StateEnum, StepEnum
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.utility import is_eda_exist
from chipcompiler.tools.ecc.plot import ECCToolsPlot
from chipcompiler.tools.ecc.metrics import build_step_metrics
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.tools.ecc.checklist import EccChecklist
from chipcompiler.utility import json_read

def create_db_engine(workspace: Workspace,
                     step: WorkspaceStep) -> ECCToolsModule:
    """"""
    if not is_eda_exist():
        return False
    eda_inst = ECCToolsModule()
    
    eda_inst.init_config(flow_config=step.config["flow"],
                         db_config=step.config["db"],
                         output_dir=step.data["dir"],
                         feature_dir=step.feature["dir"])
    
    eda_inst.init_techlef(workspace.pdk.tech)
    eda_inst.init_lefs(workspace.pdk.lefs)
    
    # if db def exist, read db def
    if os.path.exists(step.input["def"]):
        eda_inst.read_def(step.input["def"])      
    else:
        #else, read step output verilog
        if os.path.exists(step.input["verilog"]):
            eda_inst.read_verilog(verilog=step.input["verilog"],
                                  top_module=workspace.design.top_module)
        else:
            return None
    
    return eda_inst

def get_eda_instance(workspace: Workspace,
                     step: WorkspaceStep,
                     instance: ECCToolsModule=None) -> ECCToolsModule:
    """
    module is ecc module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    eda_inst = None
    if instance is not None:
        # copy data from module, but not set module to eda inst
        # TBD
        eda_inst = instance
    else:
        # init ecc module
        eda_inst = create_db_engine(workspace=workspace,
                                    step=step)
    
    return eda_inst

def save_data(workspace: Workspace,
              step: WorkspaceStep,
              module : ECCToolsModule,
              feature_step : bool = True) -> bool:
    """
    module is ecc module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if module is None:
        return FALSE
    
    module.def_save(def_path=step.output["def"])
    module.verilog_save(output_verilog=step.output["verilog"])
    module.gds_save(output_path=step.output["gds"])
    module.feature_sammry(json_path=step.feature["db"])
    if feature_step:
        module.feature_step(step=step.name,
                            json_path=step.feature["step"])
    
    module.report_summary(path=step.report["db"])
    
    # report timing
    module.init_sta(output_dir=step.data["sta"],
                    top_module=workspace.design.top_module,
                    lib_paths=workspace.pdk.libs,
                    sdc_path=workspace.pdk.sdc)
    module.report_timing()
    
    # update parameters
    db_json = json_read(step.feature["db"])
    if len(db_json) > 0: 
        from chipcompiler.data.parameter import update_parameters, save_parameter
        die_bounding_width = db_json.get("Design Layout", {}).get("die_bounding_width", 0)
        die_bounding_height = db_json.get("Design Layout", {}).get("die_bounding_height", 0)
        die_area = db_json.get("Design Layout", {}).get("die_area", 0)
        
        core_bounding_width = db_json.get("Design Layout", {}).get("core_bounding_width", 0)
        core_bounding_height = db_json.get("Design Layout", {}).get("core_bounding_height", 0)
        core_area = db_json.get("Design Layout", {}).get("core_area", 0)
        
        margin = workspace.parameters.data.get("Core", {}).get("Margin", [0, 0])
        
        update_param = {
            "Die": {
                "Size": [die_bounding_width, die_bounding_height],
                "Area": die_area
            },
            "Core": {
                "Size": [core_bounding_width, core_bounding_height],
                "Area": core_area,
                "Bounding box": "({} , {}) ({} , {})".format(
                    margin[0], 
                    margin[1], 
                    core_bounding_width + margin[0], 
                    core_bounding_height + margin[1]
                )
            }
        }
        
        update_parameters(parameters_src=update_param,
                          parameters_target=workspace.parameters.data)
        save_parameter(workspace.parameters)
    
    return True
    
def run_step(workspace: Workspace,
             step: WorkspaceStep,
             module : ECCToolsModule | None = None) -> bool:
    if not is_eda_exist():
        return False
        
    state = False
    match(step.name):
        case StepEnum.FLOORPLAN.value:
            state = run_floorplan(workspace=workspace, 
                                  step=step, 
                                  module=module)
        case StepEnum.NETLIST_OPT.value:
            state = run_net_opt(workspace=workspace, 
                                step=step, 
                                module=module)
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, 
                                  step=step, 
                                  module=module)
        case StepEnum.CTS.value:
            state = run_cts(workspace=workspace, 
                            step=step, 
                            module=module)
        case StepEnum.TIMING_OPT_DRV.value:
            state = run_timing_opt_drv(workspace=workspace, 
                                       step=step, 
                                       module=module)
        case StepEnum.TIMING_OPT_HOLD.value:
            state = run_timing_opt_hold(workspace=workspace, 
                                        step=step, 
                                        module=module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, 
                                     step=step, 
                                     module=module)
        case StepEnum.ROUTING.value:
            state = run_routing(workspace=workspace, 
                                step=step, 
                                module=module)
        case StepEnum.DRC.value:
            state = run_drc(workspace=workspace, 
                            step=step, 
                            module=module)
        case StepEnum.FILLER.value:
            state = run_filler(workspace=workspace, 
                               step=step, 
                               module=module)      
    return state

def run_analysis(workspace: Workspace,
                 step: WorkspaceStep,
                 subflow : EccSubFlow):
    # save metrics
    build_step_metrics(workspace=workspace, 
                       step=step,
                       subflow=subflow)
    
    # plot layout image
    ploter = ECCToolsPlot(workspace=workspace, 
                      step=step)
    ploter.plot()   
    
    # do checklist 
    checklist = EccChecklist(workspace=workspace, workspace_step=step)
    checklist.check()

def run_net_opt(workspace: Workspace,
                step: WorkspaceStep,
                module : ECCToolsModule = None) -> bool:
    """
    run net optimization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_net_opt(config=step.config[f"{StepEnum.NETLIST_OPT.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_net_optimization.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut
    
def run_placement(workspace: Workspace,
                  step: WorkspaceStep,
                  module : ECCToolsModule = None) -> bool:
    """
    run placement
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_placement(config=step.config[f"{StepEnum.PLACEMENT.value}"])
        eda_inst.feature_placement_map(json_path=step.feature["map"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_cts(workspace: Workspace,
            step: WorkspaceStep,
            module : ECCToolsModule = None) -> bool:
    """
    run CTS
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_cts(config=step.config[f"{StepEnum.CTS.value}"],
                         output=step.data[f"{StepEnum.CTS.value}"])
        
        eda_inst.report_cts(output=step.data[f"{StepEnum.CTS.value}"])
        
        eda_inst.run_legalize(config=step.config[f"{StepEnum.LEGALIZATION.value}"])
        
        eda_inst.feature_cts_map(json_path=step.feature["map"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_CTS.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_timing_opt_drv(workspace: Workspace,
                       step: WorkspaceStep,
                       module : ECCToolsModule = None) -> bool:
    """
    run timing optization drv
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_timing_opt_drv(config=step.config[f"{StepEnum.TIMING_OPT_DRV.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_timing_opt_drv.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
    
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_timing_opt_hold(workspace: Workspace,
                        step: WorkspaceStep,
                        module : ECCToolsModule = None) -> bool:
    """
    run timing optization hold 
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_timing_opt_hold(config=step.config[f"{StepEnum.TIMING_OPT_HOLD.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_timing_opt_hold.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_routing(workspace: Workspace,
                step: WorkspaceStep,
                module : ECCToolsModule = None) -> bool:
    """
    run routing
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        if eda_inst.is_rt_timing_enable(config=step.config[f"{StepEnum.ROUTING.value}"]):
            eda_inst.init_sta(output_dir=step.data["sta"],
                              top_module=workspace.design.top_module,
                              lib_paths=workspace.pdk.libs,
                              sdc_path=workspace.pdk.sdc)
            
        eda_inst.run_routing(config=step.config[f"{StepEnum.ROUTING.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_routing.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut


def run_drc(workspace: Workspace,
            step: WorkspaceStep,
            module : ECCToolsModule = None) -> bool:
    """
    run chip drc
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.init_drc(output_dir=step.data[f"{StepEnum.DRC.value}"])
        eda_inst.run_drc(config=step.config[f"{StepEnum.DRC.value}"],
                         report_path=step.report["step"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_DRC.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
        
        eda_inst.save_drc(feature_path=step.feature[f"step"])
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_legalization(workspace: Workspace,
                     step: WorkspaceStep,
                     module : ECCToolsModule = None) -> bool:
    """
    run placement legalization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_legalize(config=step.config[f"{StepEnum.LEGALIZATION.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_filler(workspace: Workspace,
               step: WorkspaceStep,
               module : ECCToolsModule = None) -> bool:
    """
    run placement filler
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        eda_inst.run_filler(config=step.config[f"{StepEnum.FILLER.value}"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_filler.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst)
      
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_floorplan(workspace: Workspace,
                  step: WorkspaceStep,
                  module : ECCToolsModule = None) -> bool:
    """
    run floorplan
    """
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value,
                             state=StateEnum.Success)
        
        # init floorplan
        # init by core utilization
        util = workspace.parameters.data.get("Core", {}).get("Utilitization", 0.3)
        margin = workspace.parameters.data.get("Core", {}).get("Margin", [0, 0])
        aspect_ratio = workspace.parameters.data.get("Core", {}).get("Aspect ratio", 1)
        eda_inst.init_floorplan_by_core_utilization(
                core_site=workspace.pdk.site_core,
                io_site=workspace.pdk.site_io,
                corner_site=workspace.pdk.site_corner,
                core_util=util,
                x_margin=margin[0],
                y_margin=margin[1],
                aspect_ratio=aspect_ratio,
            )
        
        # init by die and core area
        # die_area=workspace.parameters.data.get("Die", {}).get("Bounding box", "")
        # core_area=workspace.parameters.data.get("Core", {}).get("Bounding box", "")
        # eda_inst.init_floorplan_by_area(die_area=die_area,
        #                                 core_area=core_area,
        #                                 core_site=workspace.pdk.site_core,
        #                                 io_site=workspace.pdk.site_io,
        #                                 corner_site=workspace.pdk.site_corner)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.init_floorplan.value,
                             state=StateEnum.Success)
        
        json_floorplan = workspace.parameters.data.get("Floorplan", {})
        
        # create tracks
        json_track = json_floorplan.get("Tracks", [])
        for item in json_track:
            eda_inst.gern_track(layer=item.get("layer", ""),
                                x_start=item.get("x start", 0),
                                x_step=item.get("x step", 0),
                                y_start=item.get("y start", 0),
                                y_step=item.get("y step", 0))
        sub_flow.update_step(step_name=EccSubFlowEnum.create_tracks.value,
                             state=StateEnum.Success)
        
        # PDN
        json_PDN = workspace.parameters.data.get("PDN", {})
        
        # IO placement
        json_io_pins = json_PDN.get("IO", {})
        for item in json_io_pins:
            net_name = item.get("net name", "")
            direction = item.get("direction", "")
            is_power = item.get("is power")
            eda_inst.add_pdn_io(net_name=net_name,
                                direction=direction,
                                is_power=is_power)
        
        # PDN global connect
        json_global_connect = json_PDN.get("Global connect", {})
        for item in json_global_connect:
            net_name = item.get("net name", "")
            instance_pin_name = item.get("instance pin name", "")
            is_power = item.get("is power", 1)
            eda_inst.global_net_connect(net_name=net_name,
                                        instance_pin_name=instance_pin_name,
                                        is_power=is_power)
        
        # auto place io pins
        json_iopin_place = json_floorplan.get("Auto place pin", {})
        eda_inst.auto_place_pins(layer=json_iopin_place.get("layer", ""),
                                 width=json_iopin_place.get("width", 0),
                                 height=json_iopin_place.get("height", 0),
                                 sides=json_iopin_place.get("sides", []))
        sub_flow.update_step(step_name=EccSubFlowEnum.place_io_pins.value,
                             state=StateEnum.Success)
        
        # tap cell
        eda_inst.tapcell(tapcell=workspace.pdk.tap_cell,
                         distance=json_floorplan.get("Tap distance", 0),
                         endcap=workspace.pdk.end_cap)
        sub_flow.update_step(step_name=EccSubFlowEnum.tap_cell.value,
                             state=StateEnum.Success)
        
        # PDN grid
        json_pdn_grid = json_PDN.get("Grid", {})
        if len(json_pdn_grid) > 0:
            layer = json_pdn_grid.get("layer", "")
            power_net = json_pdn_grid.get("power net", "")
            ground_net = json_pdn_grid.get("ground net", "")
            width = json_pdn_grid.get("width", 0)
            offset = json_pdn_grid.get("offset", 0)
            eda_inst.create_pdn_grid(layer=layer,
                                     net_power=power_net,
                                     net_ground=ground_net,
                                     width=width,
                                     offset=offset)
        
        # PDN stripe
        # json_pdn_stripe = json_PDN.get("Stripe", {})
        # for item in json_pdn_stripe:
        #     layer = item.get("layer", "")
        #     power_net = item.get("power net", "")
        #     ground_net = item.get("ground net", "")
        #     width = item.get("width", 0)
        #     pitch = item.get("pitch", 0)
        #     offset = item.get("offset", 0)
        #     eda_inst.create_pdn_stripe(layer=layer,
        #                                net_power=power_net,
        #                                net_ground=ground_net,
        #                                width=width,
        #                                pitch=pitch,
        #                                offset=offset)
            
        # # PDN connect layers
        # json_pdn_connect_layers= json_PDN.get("Connect layers", [])
        # for item in json_pdn_connect_layers:
        #     layers = item.get("layers", [])
        #     if len(layers) >= 2:
        #         eda_inst.connect_pdn_layers(layers)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.PDN.value,
                             state=StateEnum.Success)
        
        # set clock net
        clock_name = workspace.parameters.data.get("Clock", "")
        eda_inst.set_net(net_name=clock_name,
                         net_type="CLOCK")
        sub_flow.update_step(step_name=EccSubFlowEnum.set_clock_net.value,
                             state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, module=eda_inst, feature_step=False)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
        
        return reslut
    
    return False 