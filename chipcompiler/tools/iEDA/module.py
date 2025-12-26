#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from numpy import double

class IEDAModule:
    """
    python api package of iEDA.
    """
    def __init__(self):
        try:
            from chipcompiler.tools.iEDA.utility import is_eda_exist
            if is_eda_exist():
                from chipcompiler.tools.iEDA.bin import ieda_py as ieda
        except ImportError:
            raise ImportError("iEDA tool is not installed or not found.")
    
        self.ieda = ieda

    def get_ieda(self):
        return self.ieda
    
    def exit(self):
        """exit iEDA"""
        self.ieda.flow_exit()
    
    ########################################################################
    # config api
    ########################################################################
    def init_config(self,
                    flow_config : str,
                    db_config : str,
                    output_dir : str,
                    feature_dir : str):
        """init_config"""
        self.ieda.flow_init(
            flow_config=flow_config
        )

        self.ieda.db_init(
            config_path=db_config,
            output_path=output_dir,
            feature_path=feature_dir,
        )
        
    ########################################################################
    # data api
    ########################################################################
    def set_net(self, 
                net_name: str, 
                net_type: str):
        """
        set net type
        """
        return self.ieda.set_net(net_name=net_name, net_type=net_type)
    
    def set_exclude_cell_names(self, cell_names: set):
        self.cell_names = cell_names
        
    def write_placement_back(self, 
                             dm_inst_ptr, 
                             node_x, 
                             node_y):
        self.ieda.write_placement_back(dm_inst_ptr, 
                                       node_x, 
                                       node_y)
    
    ########################################################################
    # data io api
    ########################################################################
    def init_techlef(self, tech_lef_path : str):
        """init tech lef"""
        self.ieda.tech_lef_init(tech_lef_path)

    def init_lefs(self, lef_paths: list):
        """init_lef"""
        self.ieda.lef_init(lef_paths=lef_paths)

    def read_def(self, path: str = ""):
        """init def"""
        self.ieda.def_init(def_path=path)

    def read_verilog(self, 
                     verilog : str, 
                     top_module: str):
        """init verilog"""
        self.ieda.verilog_init(verilog, 
                               top_module)

    def def_save(self, def_path: str):
        """save def file"""
        self.ieda.def_save(def_name=def_path)

    def gds_save(self, output_path: str):
        """save gds file"""
        self.ieda.gds_save(output_path)

    def tcl_save(self, output_path: str):
        """save tcl file"""
        self.ieda.tcl_save(output_path)

    def verilog_save(self, 
                     output_verilog, 
                     cell_names: set = set()):
        """verilog save"""
        self.ieda.netlist_save(
            netlist_path=output_verilog, 
            exclude_cell_names=cell_names
        )
    
    ########################################################################
    # feature api
    ########################################################################
    def feature_sammry(self, json_path: str):
        """
        generate feature summary
        """
        self.ieda.feature_summary(json_path)
        
    def feature_step(self, 
                     step: str, 
                     json_path: str):
        """
        generate step feature
        """
        self.ieda.feature_tool(json_path, step)
    
    ########################################################################
    # CTS api
    ########################################################################
    def run_cts(self, 
                config: str, 
                output : str) -> bool:
        return self.ieda.run_cts(config, output)
    
    def feature_cts_map(self, 
                        json_path: str, 
                        map_grid_size=1):
        """
        generate cts map feature
        """
        self.ieda.feature_cts_eval(json_path, map_grid_size)
    
    ########################################################################    
    # DRC api
    ########################################################################
    def init_drc(self, 
                 output_dir : str,
                 therad_number : int = 128,
                 golden_dir : str = ""):
        """
        init drc config
        """
        self.ieda.init_drc(
            temp_directory_path=output_dir,
            thread_number=therad_number,
            golden_directory_path=golden_dir)
        
    def run_drc(self, 
                config: str, 
                report_path : str) -> bool:
        """
        run drc check
        """
        self.ieda.run_drc(config=config, report=report_path)
        
    def save_drc(self, feature_path: str):
        """
        generate drc result
        """
        self.ieda.save_drc(feature_path)
    
    ########################################################################    
    # floorplan api
    ########################################################################
    def init_floorplan(self,
                       die_area: str,
                       core_area: str,
                       core_site: str,
                       io_site: str,
                       corner_site: str,
                       core_util: double,
                       x_margin: double,
                       y_margin: double,
                       xy_ratio: double,
                       cell_area: double):
        """
        init floorplan
        Example:
        die_area :  "0.0    0.0   1100    1100"
        core_area : "10.0   10.0  1090.0  1090.0"
        """
        return self.ieda.init_floorplan(
            die_area=die_area,
            core_area=core_area,
            core_site=core_site,
            io_site=io_site,
            corner_site=corner_site,
            core_util=core_util,
            x_margin=x_margin,
            y_margin=y_margin,
            xy_ratio=xy_ratio,
            cell_area=cell_area)

    def init_floorplan_by_area(
        self,
        die_area: str,
        core_area: str,
        core_site: str,
        io_site: str,
        corner_site: str):
        """
        init floorplan by die area and core area
        """
        return self.init_floorplan(
            die_area=die_area,
            core_area=core_area,
            core_site=core_site,
            io_site=io_site,
            corner_site=corner_site,
            core_util=0,
            x_margin=0,
            y_margin=0,
            xy_ratio=0,
            cell_area=0)

    def init_floorplan_by_core_utilization(
        self,
        core_site: str,
        io_site: str,
        corner_site: str,
        core_util: double,
        x_margin: double,
        y_margin: double,
        xy_ratio: double,
        cell_area: double = 0):
        """
        init floorplan by core utilization
        """
        return self.init_floorplan(
            die_area="",
            core_area="",
            core_site=core_site,
            io_site=io_site,
            corner_site=corner_site,
            core_util=core_util,
            x_margin=x_margin,
            y_margin=y_margin,
            xy_ratio=xy_ratio,
            cell_area=cell_area)

    def gern_track(self, 
                   layer: str, 
                   x_start: int, 
                   x_step: int, 
                   y_start: int, 
                   y_step: int):
        """
        generate track
        """
        return self.ieda.gern_track(
            layer=layer, 
            x_start=x_start, 
            x_step=x_step, 
            y_start=y_start, 
            y_step=y_step)

    def add_pdn_io(self, 
                   net_name: str, 
                   direction: str, 
                   is_power: bool, 
                   pin_name: str = None):
        if pin_name is None:
            pin_name = net_name
        return self.ieda.add_pdn_io(pin_name=pin_name, 
                                    net_name=net_name, 
                                    direction=direction, 
                                    is_power=is_power)

    def global_net_connect(self, 
                           net_name: str, 
                           instance_pin_name: str, 
                           is_power: bool):
        return self.ieda.global_net_connect(net_name=net_name, 
                                            instance_pin_name=instance_pin_name, 
                                            is_power=is_power)

    def auto_place_pins(self, 
                        layer: str, 
                        width: int, 
                        height: int, 
                        sides: list[str] = []):
        """
        layer : layer place io pins
        witdh : io pin width, in dbu
        height : io pin height, in dbu
        sides : "left", "rigth", "top", "bottom", if empty, place io pins around die.
        """
        return self.ieda.auto_place_pins(
            layer=layer, 
            width=width, 
            height=height, 
            sides=sides
        )

    def tapcell(self, 
                tapcell: str, 
                distance: double, 
                endcap: str):
        return self.ieda.tapcell(tapcell=tapcell, 
                                 distance=distance, 
                                 endcap=endcap)
        
    ########################################################################
    # pdn api
    ########################################################################
    def pnp(self, config: str):
        self.ieda.run_pnp(config)
    
    ########################################################################
    # placement api
    ########################################################################
    def run_placement(self, config: str):
        self.ieda.run_placer(config)
        
    def run_legalize(self, config: str):
        self.ieda.run_incremental_flow(config)
        
    def run_filler(self, config: str):
        self.ieda.run_filler(config)
        
    def run_macro_placement(self, config: str, tcl_path=""):
        """
        run macro placement
        """
        self.ieda.runMP(config, tcl_path)
        
    def run_refinement(self, tcl_path=""):
        self.ieda.runRef(tcl_path)
        
    def run_ai_placement(self,
                        config: str, 
                        onnx_path: str, 
                        normalization_path: str):
        """
        Run AI-guided placement using ONNX model

        Args:
            onnx_path: Path to the ONNX model file
            normalization_path: Path to the normalization parameters JSON file
        """
        self.ieda.run_ai_placement(config, 
                                   onnx_path, 
                                   normalization_path)
        
    def feature_macro_drc_distribution(self, 
                                       path: str, 
                                       drc_path: str):
        """
        build macro drc distribution
        """
        self.ieda.feature_macro_drc(path=path, 
                                    drc_path=drc_path)
    
    ########################################################################
    # routing api
    ########################################################################
    def run_routing(self, config: str):
        self.ieda.init_rt(config=config)
        self.ieda.run_rt()
        self.ieda.destroy_rt()
        
    def close_routing(self):
        self.ieda.destroy_rt()
        
    # read route json file to iEDA route data
    def feature_route_read(self, json_path: str):
        self.ieda.feature_route_read(path=json_path)

    # read route def and save route data to json
    def feature_route(self, json_path: str):
        self.ieda.feature_route(path=json_path)  
        
    def is_rt_timing_enable(self, config : str):
        import os
        import json
        if os.path.exists(config):
            with open(config, "r", encoding="utf-8") as f_reader:  
                json_data = json.load(f_reader)
                # check if time enable
                if json_data["RT"]["-enable_timing"] == "1":
                    return True
        return False
    
    ########################################################################
    # STA api
    ########################################################################
    def init_sta(self,
                 output_dir : str,
                 design : str,
                 lib_paths : list[str],
                 sdc_path: str):
        self.ieda.set_design_workspace(output_dir)

        self.ieda.read_liberty(lib_paths)
        self.ieda.link_design(design)
        self.ieda.read_sdc(sdc_path)
        
    def read_liberty(self, lib_paths : list[str]):
        self.ieda.read_liberty(lib_paths)
        
    def link_design(self, design : str):
        self.ieda.link_design(design)

    def read_sdc(self, sdc_path : str):
        self.ieda.read_sdc(sdc_path)
        
    def create_data_flow(self):
        self.ieda.create_data_flow()

    def get_used_libs(self):
        """
        get lib files that use in the disign
        """
        libs = self.ieda.get_used_libs()

        return libs
    ########################################################################
    # timing opt api
    ########################################################################
    def run_timing_opt_drv(self, config: str):
        self.ieda.run_to_drv(config)
        
    def run_timing_opt_hold(self, config: str):
        self.ieda.run_to_hold(config)
        
    def run_timing_opt_setup(self, config: str):
        self.ieda.run_to_setup(config)
    
    ########################################################################
    # data vectorization
    ########################################################################
    def generate_vectors(self, 
                         vectors_dir : str,
                         patch_row_step: int = 9, 
                         patch_col_step: int = 9, 
                         batch_mode: bool = True, 
                         is_placement_mode: bool = False, 
                         sta_mode: int = 0):
        """
        generate vectorized data from design
        """
        self.ieda.generate_vectors(
            dir=vectors_dir,
            patch_row_step=patch_row_step,
            patch_col_step=patch_col_step,
            batch_mode=batch_mode,
            is_placement_mode=is_placement_mode,
            sta_mode=sta_mode,
        )


    def vectors_nets_to_def(self, vectors_dir : str):
        """
        save vectorized data to def
        """
        self.ieda.read_vectors_nets(dir=vectors_dir)

    def vectors_nets_patterns_to_def(self, path):
        self.ieda.read_vectors_nets_patterns(path=path)
    
    ########################################################################
    # net optimization
    ########################################################################
    def run_net_opt(self, config : str):
        return self.ieda.run_no_fixfanout(config)