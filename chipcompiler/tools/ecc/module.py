#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from pathlib import Path
from numpy import double

class ECCToolsModule:
    """
    python api package of ECC.
    """
    def __init__(self):
        try:
            from chipcompiler.tools.ecc.utility import is_eda_exist
            if is_eda_exist():
                from chipcompiler.tools.ecc.bin import ecc_py as ecc
        except ImportError as exc:
            ecc_bin_dir = Path(__file__).resolve().parent / "bin"
            candidates = sorted(p.name for p in ecc_bin_dir.glob("ecc_py*.so"))
            raise ImportError(
                "ecc tool is not installed or not found. "
                f"Import error: {exc}. "
                f"Available ecc_py binaries in {ecc_bin_dir}: {candidates}"
            ) from exc
    
        self.ecc = ecc

    def get_ecc(self):
        return self.ecc
    
    def exit(self):
        """exit ECC tools"""
        self.ecc.flow_exit()
        
    def get_dmInst_ptr(self):
        self.ecc.get_dmInst()
        
    def pydb(
        self,
        dm_inst_ptr,
        route_num_bins_x: int,
        route_num_bins_y: int,
        routability_opt_flag: int,
        with_sta: int,
    ):
        return self.ecc.pydb(
            dm_inst_ptr,
            route_num_bins_x,
            route_num_bins_y,
            routability_opt_flag,
            with_sta,
        )

    def build_macro_connection_map(self, max_hop: int):
        return self.ecc.build_macro_connection_map(max_hop)
    
    ########################################################################
    # config api
    ########################################################################
    def init_config(self,
                    flow_config : str,
                    db_config : str,
                    output_dir : str,
                    feature_dir : str):
        """init_config"""
        self.ecc.flow_init(
            flow_config=flow_config
        )

        self.ecc.db_init(
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
        return self.ecc.set_net(net_name=net_name, net_type=net_type)
    
    def set_exclude_cell_names(self, cell_names: set):
        self.cell_names = cell_names
        
    def write_placement_back(self, 
                             dm_inst_ptr, 
                             node_x, 
                             node_y):
        self.ecc.write_placement_back(dm_inst_ptr, 
                                       node_x, 
                                       node_y)
    
    ########################################################################
    # data io api
    ########################################################################
    def init_techlef(self, tech_lef_path : str):
        """init tech lef"""
        self.ecc.tech_lef_init(tech_lef_path)

    def init_lefs(self, lef_paths: list):
        """init_lef"""
        self.ecc.lef_init(lef_paths=lef_paths)

    def read_def(self, path: str = ""):
        """init def"""
        self.ecc.def_init(def_path=path)

    def read_verilog(self, 
                     verilog : str, 
                     top_module: str):
        """init verilog"""
        self.ecc.verilog_init(verilog, 
                               top_module)

    def def_save(self, def_path: str):
        """save def file"""
        self.ecc.def_save(def_name=def_path)

    def gds_save(self, output_path: str):
        """save gds file"""
        self.ecc.gds_save(output_path)

    def tcl_save(self, output_path: str):
        """save tcl file"""
        self.ecc.tcl_save(output_path)

    def verilog_save(self, 
                     output_verilog, 
                     cell_names: set = set()):
        """verilog save"""
        self.ecc.netlist_save(
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
        self.ecc.feature_summary(json_path)
        
    def feature_step(self, 
                     step: str, 
                     json_path: str):
        """
        generate step feature
        """
        self.ecc.feature_tool(json_path, step)
        
    ########################################################################
    # reports api
    ########################################################################
    def report_summary(self, 
                       path: str):
        """
        generate step report
        """
        self.ecc.report_db(path)
        
    ########################################################################
    # CTS api
    ########################################################################
    def run_cts(self, 
                config: str, 
                output : str) -> bool:
        return self.ecc.run_cts(config, output)
    
    def report_cts(self, output : str):
        self.ecc.cts_report(output)
    
    def feature_cts_map(self, 
                        json_path: str, 
                        map_grid_size=1):
        """
        generate cts map feature
        """
        self.ecc.feature_cts_eval(json_path, map_grid_size)
    
    ########################################################################    
    # DRC api
    ########################################################################
    def init_drc(self, 
                 output_dir : str,
                 therad_number : int = 128):
        """
        init drc config
        """
        self.ecc.init_drc(
            temp_directory_path=output_dir,
            thread_number=therad_number)
        
    def run_drc(self, 
                config: str, 
                report_path : str="") -> bool:
        """
        run drc check
        """
        self.ecc.run_drc(config=config, report=report_path)
        
    def save_drc(self, feature_path: str):
        """
        generate drc result
        """
        self.ecc.save_drc(path=feature_path)
    
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
                       aspect_ratio: double,
                       cell_area: double):
        """
        init floorplan
        Example:
        die_area :  "0.0    0.0   1100    1100"
        core_area : "10.0   10.0  1090.0  1090.0"
        """
        return self.ecc.init_floorplan(
            die_area=die_area,
            core_area=core_area,
            core_site=core_site,
            io_site=io_site,
            corner_site=corner_site,
            core_util=core_util,
            x_margin=x_margin,
            y_margin=y_margin,
            xy_ratio=aspect_ratio,
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
            aspect_ratio=0,
            cell_area=0)

    def init_floorplan_by_core_utilization(
        self,
        core_site: str,
        io_site: str,
        corner_site: str,
        core_util: double,
        x_margin: double,
        y_margin: double,
        aspect_ratio: double,
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
            aspect_ratio=aspect_ratio,
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
        return self.ecc.gern_track(
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
        return self.ecc.add_pdn_io(pin_name=pin_name, 
                                    net_name=net_name, 
                                    direction=direction, 
                                    is_power=is_power)

    def global_net_connect(self, 
                           net_name: str, 
                           instance_pin_name: str, 
                           is_power: bool):
        return self.ecc.global_net_connect(net_name=net_name, 
                                            instance_pin_name=instance_pin_name, 
                                            is_power=is_power)
        
    def create_pdn_grid(self,
                        layer : str,
                        net_power : str,
                        net_ground : str,
                        width : double,
                        offset : double):
        return self.ecc.create_grid(layer_name=layer,
                                     net_name_power=net_power,
                                     net_name_ground=net_ground,
                                     width=width,
                                     offset=offset)
        
    def create_pdn_stripe(self,
                          layer : str,
                          net_power : str,
                          net_ground : str,
                          width : double,
                          pitch : double,
                          offset : double):
        return self.ecc.create_stripe(layer_name=layer,
                                       net_name_power=net_power,
                                       net_name_ground=net_ground,
                                       width=width,
                                       pitch=pitch,
                                       offset=offset)
        
    def connect_pdn_layers(self,
                           layers : list[str]):
        return self.ecc.connect_two_layer(layers=layers)

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
        return self.ecc.auto_place_pins(
            layer=layer, 
            width=width, 
            height=height, 
            sides=sides
        )

    def tapcell(self, 
                tapcell: str, 
                distance: double, 
                endcap: str):
        return self.ecc.tapcell(tapcell=tapcell, 
                                 distance=distance, 
                                 endcap=endcap)
        
    ########################################################################
    # pdn api
    ########################################################################
    def pnp(self, config: str):
        self.ecc.run_pnp(config)
    
    ########################################################################
    # placement api
    ########################################################################
    def run_placement(self, config: str):
        self.ecc.run_placer(config)
        
    def feature_placement_map(self, json_path: str, map_grid_size=1):
        """
        generate placement map feature
        """
        self.ecc.feature_pl_eval(json_path, map_grid_size)
        
    def run_legalize(self, config: str):
        self.ecc.run_incremental_lg()
        
    def run_filler(self, config: str):
        self.ecc.run_filler(config)
        
    def run_macro_placement(self, config: str, tcl_path=""):
        """
        run macro placement
        """
        self.ecc.runMP(config, tcl_path)
        
    def run_refinement(self, tcl_path=""):
        self.ecc.runRef(tcl_path)
        
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
        self.ecc.run_ai_placement(config, 
                                   onnx_path, 
                                   normalization_path)
        
    def feature_macro_drc_distribution(self, 
                                       path: str, 
                                       drc_path: str):
        """
        build macro drc distribution
        """
        self.ecc.feature_macro_drc(path=path, 
                                    drc_path=drc_path)
    
    ########################################################################
    # routing api
    ########################################################################
    def run_routing(self, config: str):
        self.ecc.init_rt(config=config)
        self.ecc.run_rt()
        self.ecc.destroy_rt()
        
    def close_routing(self):
        self.ecc.destroy_rt()
        
    # read route json file to ecc route data
    def feature_route_read(self, json_path: str):
        self.ecc.feature_route_read(path=json_path)

    # read route def and save route data to json
    def feature_route(self, json_path: str):
        self.ecc.feature_route(path=json_path)  
        
    def is_rt_timing_enable(self, config : str):
        import os
        import json
        if os.path.exists(config):
            with open(config, "r", encoding="utf-8") as f_reader:  
                json_data = json.load(f_reader)
                # check if time enable
                if json_data is not None and json_data.get("RT", {}).get("-enable_timing", "0") == "1":
                    return True
        return False
    
    ########################################################################
    # STA api
    ########################################################################
    def init_sta(self,
                 output_dir : str,
                 top_module : str,
                 lib_paths : list[str],
                 sdc_path: str):
        self.ecc.init_sta(output=output_dir)

        # self.ecc.run_sta(output=output_dir)
        # self.ecc.set_design_workspace(output_dir)

        # self.ecc.read_liberty(lib_paths)
        # self.ecc.link_design(top_module)
        # self.ecc.read_sdc(sdc_path)
        
    def read_liberty(self, lib_paths : list[str]):
        self.ecc.read_liberty(lib_paths)
        
    def link_design(self, design : str):
        self.ecc.link_design(design)

    def read_sdc(self, sdc_path : str):
        self.ecc.read_sdc(sdc_path)
        
    def create_data_flow(self):
        self.ecc.create_data_flow()

    def get_used_libs(self):
        """
        get lib files that use in the disign
        """
        libs = self.ecc.get_used_libs()

        return libs
    
    def report_timing(self,
                      digits: int = 3,
                      delay_type: str = "max_min",
                      exclude_cell_names: list[str] = [],
                      derate: bool = False,
                      is_clock_cap: bool = False,
                      is_not_bak_rpt: bool = True,
                      max_path: int = 3,
                      nworst: int = 1,
                      from_list: list[str] = [],
                      through: list[list[str]] = [],
                      to_list: list[str] = [],
                      is_json: bool = True):
        """
        report timing
        """       
        self.ecc.report_timing(
            digits=digits,
            delay_type=delay_type,
            exclude_cell_names=exclude_cell_names,
            derate=derate,
            is_clock_cap=is_clock_cap,
            is_not_bak_rpt=is_not_bak_rpt,
            max_path=max_path,
            nworst=nworst,
            from_list=from_list,
            through=through,
            to_list=to_list,
            is_json=is_json,
        )
        
    ########################################################################
    # timing opt api
    ########################################################################
    def run_timing_opt_drv(self, config: str):
        self.ecc.run_to_drv(config)
        
    def run_timing_opt_hold(self, config: str):
        self.ecc.run_to_hold(config)
        
    def run_timing_opt_setup(self, config: str):
        self.ecc.run_to_setup(config)
    
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
        self.ecc.generate_vectors(
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
        self.ecc.read_vectors_nets(dir=vectors_dir)

    def vectors_nets_patterns_to_def(self, path):
        self.ecc.read_vectors_nets_patterns(path=path)
    
    ########################################################################
    # net optimization
    ########################################################################
    def run_net_opt(self, config : str):
        return self.ecc.run_no_fixfanout(config)
