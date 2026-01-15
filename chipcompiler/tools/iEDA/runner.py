#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os
       
from chipcompiler.data import WorkspaceStep, Workspace, StateEnum, StepEnum
from chipcompiler.tools.iEDA.module import IEDAModule
from chipcompiler.tools.iEDA.utility import is_eda_exist
from chipcompiler.tools.iEDA.plot import IEDAPlot
from chipcompiler.tools.iEDA.metrics import build_step_metrics 

def create_db_engine(workspace: Workspace,
                     step: WorkspaceStep) -> IEDAModule:
    """"""
    if not is_eda_exist():
        return False
    
    from chipcompiler.tools.iEDA.module import IEDAModule
    eda_inst = IEDAModule()
    
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
                 instance: IEDAModule=None) -> IEDAModule:
    """
    module is iEDA module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    eda_inst = None
    if instance is not None:
        # copy data from module, but not set module to eda inst
        # TBD
        eda_inst = instance
    else:
        # init iEDA module
        eda_inst = create_db_engine(workspace=workspace,
                                    step=step)
    
    return eda_inst

def save_data(step: WorkspaceStep,
              module : IEDAModule) -> bool:
    """
    module is iEDA module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if module is None:
        return FALSE
    
    module.def_save(def_path=step.output["def"])
    module.verilog_save(output_verilog=step.output["verilog"])
    module.gds_save(output_path=step.output["gds"])
    module.feature_sammry(json_path=step.feature["db"])
    module.feature_step(step=step.name,
                        json_path=step.feature["step"])
    
    module.report_summary(path=step.report["db"])
    
    return True
    
def run_step(workspace: Workspace,
             step: WorkspaceStep,
             module : IEDAModule = None) -> bool:
    if not is_eda_exist():
        return StateEnum.Invalid
        
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
            
    if state:
        # save metrics
        build_step_metrics(workspace=workspace, 
                           step=step)
        
        # plot layout image
        ploter = IEDAPlot(workspace=workspace, 
                          step=step)
        ploter.plot()   
            
    return state

def run_net_opt(workspace: Workspace,
                step: WorkspaceStep,
                module : IEDAModule = None) -> bool:
    """
    run net optimization
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    if eda_inst is not None:
        eda_inst.run_net_opt(config=step.config[f"{StepEnum.NETLIST_OPT.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False
    
def run_placement(workspace: Workspace,
                  step: WorkspaceStep,
                  module : IEDAModule = None) -> bool:
    """
    run placement
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_placement(config=step.config[f"{StepEnum.PLACEMENT.value}"])
        eda_inst.feature_placement_map(json_path=step.feature["map"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_cts(workspace: Workspace,
            step: WorkspaceStep,
            module : IEDAModule = None) -> bool:
    """
    run CTS
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_cts(config=step.config[f"{StepEnum.CTS.value}"],
                         output=step.data[f"{StepEnum.CTS.value}"])
        
        eda_inst.report_cts(output=step.data[f"{StepEnum.CTS.value}"])
        
        eda_inst.run_legalize(config=step.config[f"{StepEnum.LEGALIZATION.value}"])
        
        eda_inst.feature_cts_map(json_path=step.feature["map"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_timing_opt_drv(workspace: Workspace,
                       step: WorkspaceStep,
                       module : IEDAModule = None) -> bool:
    """
    run timing optization drv
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_timing_opt_drv(config=step.config[f"{StepEnum.TIMING_OPT_DRV.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_timing_opt_hold(workspace: Workspace,
                        step: WorkspaceStep,
                        module : IEDAModule = None) -> bool:
    """
    run timing optization hold 
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_timing_opt_hold(config=step.config[f"{StepEnum.TIMING_OPT_HOLD.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_routing(workspace: Workspace,
                step: WorkspaceStep,
                module : IEDAModule = None) -> bool:
    """
    run routing
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    
    if eda_inst is not None:
        if eda_inst.is_rt_timing_enable(config=step.config[f"{StepEnum.ROUTING.value}"]):
            eda_inst.init_sta(output_dir=step.data["sta"],
                              design=workspace.design.name,
                              lib_paths=workspace.pdk.libs,
                              sdc_path=workspace.pdk.sdc)
            
        eda_inst.run_routing(config=step.config[f"{StepEnum.ROUTING.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False


def run_drc(workspace: Workspace,
            step: WorkspaceStep,
            module : IEDAModule = None) -> bool:
    """
    run chip drc
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    
    if eda_inst is not None:
        eda_inst.init_drc(output_dir=step.data[f"{StepEnum.DRC.value}"])
        eda_inst.run_drc(config=step.config[f"{StepEnum.DRC.value}"],
                         report_path=step.report["step"])
        
        save_data(step=step, module=eda_inst)
        
        eda_inst.save_drc(feature_path=step.feature[f"step"])
        
        return True
    
    return False

def run_legalization(workspace: Workspace,
                     step: WorkspaceStep,
                     module : IEDAModule = None) -> bool:
    """
    run placement legalization
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_legalize(config=step.config[f"{StepEnum.LEGALIZATION.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_filler(workspace: Workspace,
               step: WorkspaceStep,
               module : IEDAModule = None) -> bool:
    """
    run placement filler
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
        eda_inst.run_filler(config=step.config[f"{StepEnum.FILLER.value}"])
        
        return save_data(step=step, module=eda_inst)
    
    return False

def run_floorplan(workspace: Workspace,
                  step: WorkspaceStep,
                  module : IEDAModule = None) -> bool:
    """
    run floorplan
    """
    eda_inst = get_eda_instance(workspace=workspace,
                                step=step,
                                instance=module)
    
    if eda_inst is not None:
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
        
        json_floorplan = workspace.parameters.data.get("Floorplan", {})
        
        # create tracks
        json_track = json_floorplan.get("Tracks", [])
        for item in json_track:
            eda_inst.gern_track(layer=item.get("layer", ""),
                                x_start=item.get("x start", 0),
                                x_step=item.get("x step", 0),
                                y_start=item.get("y start", 0),
                                y_step=item.get("y step", 0))
        
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
        
        # tap cell
        eda_inst.tapcell(tapcell=workspace.pdk.tap_cell,
                         distance=json_floorplan.get("Tap distance", 0),
                         endcap=workspace.pdk.end_cap)
        
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
        
        # set clock net
        clock_name = workspace.parameters.data.get("Clock", "")
        eda_inst.set_net(net_name=clock_name,
                         net_type="CLOCK")
                
            
        return save_data(step=step, module=eda_inst)
    
    return False 