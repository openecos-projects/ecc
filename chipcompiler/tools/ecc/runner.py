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
    def load_data():   
        ecc_module = ECCToolsModule()
        
        ecc_module.init_config(flow_config=workspace.config.get("flow"),
                             db_config=workspace.config.get("db"),
                             output_dir=step.data.get("dir"),
                             feature_dir=step.feature.get("dir"))
    
        db_path = step.input.get("db", "")
        if ecc_module.is_db_data_exists(db_path):
            ecc_module.load_data(path=db_path)
            workspace.logger.info(f"Successfully loaded data from {db_path}")
            return ecc_module
        else:
            return None
        
    def load_design():
        ecc_module = ECCToolsModule()
    
        ecc_module.init_config(flow_config=workspace.config.get("flow"),
                             db_config=workspace.config.get("db"),
                             output_dir=step.data.get("dir"),
                             feature_dir=step.feature.get("dir"))

        ecc_module.init_techlef(workspace.pdk.tech)
        ecc_module.init_lefs(workspace.pdk.lefs)
        
        # if db def exist, read db def
        if os.path.exists(step.input.get("def", "")):
            ecc_module.read_def(step.input.get("def", ""))      
        else:
            #else, read step output verilog
            if os.path.exists(step.input.get("verilog", "")):
                ecc_module.read_verilog(verilog=step.input.get("verilog", ""),
                                      top_module=workspace.design.top_module)
            else:
                return None
    
        return ecc_module
    
    def is_enable_setup():
        # skip synthesis step
        if step.name == StepEnum.SYNTHESIS.value:
            return False
        
        # db_path = step.input.get("db", "")
        
        # ecc_module = ECCToolsModule()
        
        # return ecc_module.is_db_data_exists(db_path) or os.path.exists(step.input.get("def", "")) or os.path.exists(step.input.get("verilog", ""))
        return os.path.exists(step.input.get("def", "")) or os.path.exists(step.input.get("verilog", ""))
    
    if not is_eda_exist() or not is_enable_setup():
        return None
    try:
        ecc_module = load_data()
        if ecc_module is None:
            ecc_module = load_design()
    except Exception as e:
        ecc_module = load_design()
        
    return ecc_module
        
def get_eda_instance(workspace: Workspace,
                     step: WorkspaceStep,
                     ecc_module: ECCToolsModule=None) -> ECCToolsModule:
    """
    ecc_module is ecc module from db engine, 
    eda instacnce may initialize data from this module if ecc_module has been set
    """
    if ecc_module is None:
        try:
            ecc_module = create_db_engine(workspace=workspace,
                                          step=step)
        except Exception as e:
            ecc_module = None
            workspace.logger.error(f"Failed to create ECC engine for step {step.name}: {e}")
            
    # release sta for some memory leakage issue
    if ecc_module is not None:
        ecc_module.update_step_paths(
            output_dir=step.data.get("dir", ""),
            feature_dir=step.feature.get("dir", ""),
        )
        ecc_module.release_sta()
    
    return ecc_module

def save_data(workspace: Workspace,
              step: WorkspaceStep,
              ecc_module : ECCToolsModule,
              feature_step : bool = True) -> bool:
    """
    module is ecc module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if ecc_module is None:
        return FALSE
    
    ecc_module.def_save(def_path=step.output.get("def", ""))
    ecc_module.verilog_save(output_verilog=step.output.get("verilog", ""))
    ecc_module.gds_save(output_path=step.output.get("gds", ""))
    ecc_module.save_data(path=step.output.get("db", ""))
    ecc_module.json_save(path=step.output.get("json", ""))
    ecc_module.feature_sammry(json_path=step.feature.get("db", ""))
    if feature_step:
        ecc_module.feature_step(step=step.name,
                            json_path=step.feature.get("step", ""))
    
    ecc_module.report_summary(path=step.report.get("db", ""))
    
    # report timing
    ecc_module.release_sta()
    ecc_module.init_sta(output_dir=step.data.get("sta", ""),
                    top_module=workspace.design.top_module,
                    lib_paths=workspace.pdk.libs,
                    sdc_path=workspace.pdk.sdc)
    ecc_module.report_timing()
    ecc_module.release_sta()
    
    # update parameters
    db_json = json_read(step.feature.get("db", ""))
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
             ecc_module : ECCToolsModule | None = None) -> bool:
    if not is_eda_exist():
        return StateEnum.Invalid
        
    state = False
    match(step.name):
        case StepEnum.FLOORPLAN.value:
            state = run_floorplan(workspace=workspace, 
                                  step=step, 
                                  ecc_module=ecc_module)
        case StepEnum.NETLIST_OPT.value:
            state = run_net_opt(workspace=workspace, 
                                step=step, 
                                ecc_module=ecc_module)
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, 
                                  step=step, 
                                  ecc_module=ecc_module)
        case StepEnum.CTS.value:
            state = run_cts(workspace=workspace, 
                            step=step, 
                            ecc_module=ecc_module)
        case StepEnum.TIMING_OPT_DRV.value:
            state = run_timing_opt_drv(workspace=workspace, 
                                       step=step, 
                                       ecc_module=ecc_module)
        case StepEnum.TIMING_OPT_HOLD.value:
            state = run_timing_opt_hold(workspace=workspace, 
                                        step=step, 
                                        ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, 
                                     step=step, 
                                     ecc_module=ecc_module)
        case StepEnum.ROUTING.value:
            state = run_routing(workspace=workspace, 
                                step=step, 
                                ecc_module=ecc_module)
        case StepEnum.DRC.value:
            state = run_drc(workspace=workspace, 
                            step=step, 
                            ecc_module=ecc_module)
        case StepEnum.FILLER.value:
            state = run_filler(workspace=workspace, 
                               step=step, 
                               ecc_module=ecc_module)  
        case StepEnum.HARDEN.value:
            state = run_harden(workspace=workspace,
                               step=step, 
                               ecc_module=ecc_module)
            
        case StepEnum.RCX.value:
            state = run_rcx(workspace=workspace,
                            step=step, 
                            ecc_module=ecc_module)
        case StepEnum.STA.value:
            state = run_sta(workspace=workspace,
                            step=step, 
                            ecc_module=ecc_module)
                
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
                ecc_module : ECCToolsModule = None) -> bool:
    """
    run net optimization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_net_opt(config=workspace.config.get(f"{StepEnum.NETLIST_OPT.value}"))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_net_optimization.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut
    
def run_placement(workspace: Workspace,
                  step: WorkspaceStep,
                  ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_placement(config=workspace.config.get(f"{StepEnum.PLACEMENT.value}"))
        ecc_module.feature_placement_map(json_path=step.feature.get("map", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_cts(workspace: Workspace,
            step: WorkspaceStep,
            ecc_module : ECCToolsModule = None) -> bool:
    """
    run CTS
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_cts(config=workspace.config.get(f"{StepEnum.CTS.value}", ""),
                         output=step.data.get(f"{StepEnum.CTS.value}", ""))
        
        ecc_module.report_cts(output=step.data.get(f"{StepEnum.CTS.value}", ""))
        
        # Post-CTS legalization is handled by the following DreamPlace legalization step.
        # ecc_module.run_legalize(config=workspace.config.get(f"{StepEnum.LEGALIZATION.value}", ""))
        
        ecc_module.feature_cts_map(json_path=step.feature.get("map", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_CTS.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_timing_opt_drv(workspace: Workspace,
                       step: WorkspaceStep,
                       ecc_module : ECCToolsModule = None) -> bool:
    """
    run timing optization drv
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_timing_opt_drv(config=workspace.config.get(f"{StepEnum.TIMING_OPT_DRV.value}", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_timing_opt_drv.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
    
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_timing_opt_hold(workspace: Workspace,
                        step: WorkspaceStep,
                        ecc_module : ECCToolsModule = None) -> bool:
    """
    run timing optization hold 
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_timing_opt_hold(config=workspace.config.get(f"{StepEnum.TIMING_OPT_HOLD.value}", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_timing_opt_hold.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_routing(workspace: Workspace,
                step: WorkspaceStep,
                ecc_module : ECCToolsModule = None) -> bool:
    """
    run routing
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        if ecc_module.is_rt_timing_enable(config=workspace.config.get(f"{StepEnum.ROUTING.value}", "")):
            ecc_module.init_sta(output_dir=step.data.get(f"{StepEnum.ROUTING.value}", ""),
                              top_module=workspace.design.top_module,
                              lib_paths=workspace.pdk.libs,
                              sdc_path=workspace.pdk.sdc)
            
        ecc_module.run_routing(config=workspace.config.get(f"{StepEnum.ROUTING.value}", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_routing.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut


def run_drc(workspace: Workspace,
            step: WorkspaceStep,
            ecc_module : ECCToolsModule = None) -> bool:
    """
    run chip drc
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.init_drc(output_dir=step.data.get(f"{StepEnum.DRC.value}", ""))
        ecc_module.run_drc(config=workspace.config.get(f"{StepEnum.DRC.value}", ""),
                         report_path=step.report.get("step", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_DRC.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
        
        ecc_module.save_drc(feature_path=step.feature.get("step", ""))
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
    
    return reslut

def run_legalization(workspace: Workspace,
                     step: WorkspaceStep,
                     ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement legalization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_legalize(config=workspace.config.get(f"{StepEnum.LEGALIZATION.value}", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_filler(workspace: Workspace,
               step: WorkspaceStep,
               ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement filler
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.run_filler(config=workspace.config.get(f"{StepEnum.FILLER.value}", ""))
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_filler.value, state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
      
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut

def run_floorplan(workspace: Workspace,
                  step: WorkspaceStep,
                  ecc_module : ECCToolsModule = None) -> bool:
    """
    run floorplan
    """
    reslut = False
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value,
                             state=StateEnum.Success)
        
        # init floorplan
        # init by core utilization
        util = workspace.parameters.data.get("Core", {}).get("Utilitization", 0.3)
        margin = workspace.parameters.data.get("Core", {}).get("Margin", [0, 0])
        aspect_ratio = workspace.parameters.data.get("Core", {}).get("Aspect ratio", 1)
        ecc_module.init_floorplan_by_core_utilization(
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
        # ecc_module.init_floorplan_by_area(die_area=die_area,
        #                                 core_area=core_area,
        #                                 core_site=workspace.pdk.site_core,
        #                                 io_site=workspace.pdk.site_io,
        #                                 corner_site=workspace.pdk.site_corner)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.init_floorplan.value,
                             state=StateEnum.Success)
        
        floorplan_dict = json_read(workspace.config.get(StepEnum.FLOORPLAN.value, ""))
        
        # create tracks
        json_floorplan = floorplan_dict.get("Floorplan", {})
        json_track = json_floorplan.get("Tracks", [])
        for item in json_track:
            ecc_module.gern_track(layer=item.get("layer", ""),
                                x_start=item.get("x start", 0),
                                x_step=item.get("x step", 0),
                                y_start=item.get("y start", 0),
                                y_step=item.get("y step", 0))
        sub_flow.update_step(step_name=EccSubFlowEnum.create_tracks.value,
                             state=StateEnum.Success)
        
        # Macro Placement
        json_macro_placement = floorplan_dict.get("Macro Placement", [])
        if len(json_macro_placement) > 0:
            for item in json_macro_placement:
                ecc_module.place_instance(
                    inst_name=item.get("inst_name", ""),
                    llx=item.get("llx", 0),
                    lly=item.get("lly", 0),
                    orient=item.get("orient", ""),
                    cellmaster=item.get("cellmaster", ""),
                    source=item.get("source", ""),
                )
        
        # PDN
        json_PDN = floorplan_dict.get("PDN", {})
        
        # IO placement
        json_io_pins = json_PDN.get("IO", {})
        for item in json_io_pins:
            net_name = item.get("net name", "")
            direction = item.get("direction", "")
            is_power = item.get("is power")
            ecc_module.add_pdn_io(net_name=net_name,
                                direction=direction,
                                is_power=is_power)
        
        # PDN global connect
        json_global_connect = json_PDN.get("Global connect", {})
        for item in json_global_connect:
            net_name = item.get("net name", "")
            instance_pin_name = item.get("instance pin name", "")
            is_power = item.get("is power", 1)
            ecc_module.global_net_connect(net_name=net_name,
                                        instance_pin_name=instance_pin_name,
                                        is_power=is_power)
        
        # auto place io pins
        json_iopin_place = json_floorplan.get("Auto place pin", {})
        ecc_module.auto_place_pins(layer=json_iopin_place.get("layer", ""),
                                 width=json_iopin_place.get("width", 0),
                                 height=json_iopin_place.get("height", 0),
                                 sides=json_iopin_place.get("sides", []))
        sub_flow.update_step(step_name=EccSubFlowEnum.place_io_pins.value,
                             state=StateEnum.Success)
        
        # tap cell
        ecc_module.tapcell(tapcell=workspace.pdk.tap_cell,
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
            ecc_module.create_pdn_grid(layer=layer,
                                     net_power=power_net,
                                     net_ground=ground_net,
                                     width=width,
                                     offset=offset)
        
        # PDN stripe
        json_pdn_stripe = json_PDN.get("Stripe", {})
        for item in json_pdn_stripe:
            layer = item.get("layer", "")
            power_net = item.get("power net", "")
            ground_net = item.get("ground net", "")
            width = item.get("width", 0)
            pitch = item.get("pitch", 0)
            offset = item.get("offset", 0)
            ecc_module.create_pdn_stripe(layer=layer,
                                       net_power=power_net,
                                       net_ground=ground_net,
                                       width=width,
                                       pitch=pitch,
                                       offset=offset)
            
        # PDN connect layers
        json_pdn_connect_layers= json_PDN.get("Connect layers", [])
        for item in json_pdn_connect_layers:
            layers = item.get("layers", [])
            if len(layers) >= 2:
                ecc_module.connect_pdn_layers(layers)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.PDN.value,
                             state=StateEnum.Success)
        
        # set clock net
        clock_name = workspace.parameters.data.get("Clock", "")
        ecc_module.set_net(net_name=clock_name,
                         net_type="CLOCK")
        sub_flow.update_step(step_name=EccSubFlowEnum.set_clock_net.value,
                             state=StateEnum.Success)
        
        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False)
            
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut 

def run_harden(workspace: Workspace,
               step: WorkspaceStep,
               ecc_module : ECCToolsModule = None) -> bool:
    """
    run harden, save design as Lef Macro and extract lib
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        ecc_module.init_sta(output_dir=step.data["sta"],
                          top_module=workspace.design.top_module,
                          lib_paths=workspace.pdk.libs,
                          sdc_path=workspace.pdk.sdc)
        ecc_module.update_timing()
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        ecc_module.write_abstract_lef(output_lef_path=step.output.get("lef", ""))
        ecc_module.write_timing_model(output_lib_path=step.output.get("lib", ""))
        ecc_module.gds_save(output_path=step.output.get("gds", ""), is_harden=True)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_harden.value, state=StateEnum.Success)
        
        reslut = True
    
    return reslut

def run_rcx(workspace: Workspace,
            step: WorkspaceStep,
            ecc_module : ECCToolsModule = None) -> bool:
    """
    run rcx
    """
    def run_jsons_to_itf(ecc_module : ECCToolsModule) -> bool:
        config=json_read(workspace.config.get(StepEnum.RCX.value, ""))
        corners_dict = config.get("corners", [])
        for item in corners_dict:
            json_file = item.get("ecc_tf", "")
            itf_file = item.get("itf_file", "")

            if not os.path.exists(json_file):
                return False
            
            ecc_module.rcx_json_to_itf(json_path=json_file, itf_path=itf_file)
        return True
    
    result = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        if not run_jsons_to_itf(ecc_module):
            sub_flow.update_step(step_name=EccSubFlowEnum.run_rcx.value, state=StateEnum.Imcomplete)
            result = False
        else:
            ecc_module.init_rcx(config=workspace.config.get(StepEnum.RCX.value, ""))
            ecc_module.run_rcx()
            ecc_module.report_rcx()
            sub_flow.update_step(step_name=EccSubFlowEnum.run_rcx.value, state=StateEnum.Success)
            
            save_data(workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False)
            
            sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                                 state=StateEnum.Success) 
        
            result = True
        
    return result


def run_sta(workspace: Workspace,
            step: WorkspaceStep,
            ecc_module : ECCToolsModule = None) -> bool:
    """
    run sta
    """
    def spef_type_from_path(spef_file: str) -> str:
        stem = os.path.splitext(os.path.basename(spef_file))[0]
        design_prefix = f"{workspace.design.name}_"
        if stem.startswith(design_prefix):
            stem = stem[len(design_prefix):]
        return stem

    def safe_dir_name(name: str) -> str:
        value = "".join(
            char if char.isalnum() or char in ("-", "_", ".") else "_"
            for char in name.strip()
        )
        return value or "spef"

    def collect_spef_files() -> list[tuple[str, str]]:
        spef_files = step.output.get("spef", [])
        if spef_files:
            return [
                (safe_dir_name(spef_type_from_path(spef_file)), spef_file)
                for spef_file in spef_files
            ]

        config = json_read(workspace.config.get(StepEnum.RCX.value, ""))
        spef_items = []
        for corner in config.get("corners", []):
            spef_file = corner.get("spef_file", "")
            if not spef_file:
                continue

            spef_type = corner.get("name", "") or spef_type_from_path(spef_file)
            spef_items.append((safe_dir_name(spef_type), spef_file))

        return spef_items

    result = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = get_eda_instance(workspace=workspace,
                                step=step,
                                ecc_module = ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        spef_items = collect_spef_files()
        if len(spef_items) <= 0:
            workspace.logger.error("No SPEF files found for STA")
            sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value,
                                 state=StateEnum.Imcomplete)
            return False

        for spef_type, spef_file in spef_items:
            if not os.path.exists(spef_file):
                workspace.logger.error("SPEF file does not exist: %s", spef_file)
                sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value,
                                     state=StateEnum.Imcomplete)
                return False
            if not os.path.exists(step.input.get("verilog", "")):
                workspace.logger.error("STA netlist does not exist: %s",
                                       step.input.get("verilog", ""))
                sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value,
                                     state=StateEnum.Imcomplete)
                return False
            if len(workspace.pdk.libs) <= 0 \
                or any(not os.path.exists(lib_path) for lib_path in workspace.pdk.libs):
                workspace.logger.error("STA liberty file does not exist: %s",
                                       workspace.pdk.libs)
                sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value,
                                     state=StateEnum.Imcomplete)
                return False
            if not os.path.exists(workspace.pdk.sdc):
                workspace.logger.error("STA SDC does not exist: %s",
                                       workspace.pdk.sdc)
                sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value,
                                     state=StateEnum.Imcomplete)
                return False

            report_dir = os.path.join(step.output.get("dir", ""), spef_type)
            os.makedirs(report_dir, exist_ok=True)

            try:
                ecc_module.set_design_workspace(report_dir)
                ecc_module.read_netlist(step.input.get("verilog", ""))
                ecc_module.read_liberty(workspace.pdk.libs)
                ecc_module.link_design(workspace.design.top_module)
                ecc_module.read_sdc(workspace.pdk.sdc)
                ecc_module.read_spef(file_name=spef_file)
                ecc_module.report_timing()
            finally:
                # release sta
                ecc_module.release_sta()

            workspace.logger.info("STA report for %s saved to %s",
                                  spef_file,
                                  report_dir)

        sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Success)
        
        result = save_data(workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
    return result
