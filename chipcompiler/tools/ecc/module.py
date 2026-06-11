#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from pathlib import Path
from numpy import double
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

class ECCToolsModule:
    """
    python api package of ECC.
    """
    def __init__(self):
        try:
            from ecc_tools_bin import ecc_py as ecc
        except ImportError:
            try:
                from chipcompiler.tools.ecc.bin import ecc_py as ecc
            except ImportError as exc:
                ecc_bin_dir = Path(__file__).resolve().parent / "bin"
                candidates = sorted(p.name for p in ecc_bin_dir.glob("ecc_py*.so"))
                raise ImportError(
                    "ecc-tools is not installed. Install the ecc-tools wheel or "
                    "build from source with: bazel run //:prepare_dev. "
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
        return self.ecc.get_dmInst()
        
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

    def build_connection_map(self, clusters, src_instances, max_hop: int):
        return self.ecc.build_connection_map(clusters, src_instances, max_hop)

    def reset_data(self):
        self.ecc.reset_data()

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

    def update_step_paths(self, output_dir: str, feature_dir: str):
        self.ecc.db_init(
            output_path=output_dir,
            feature_path=feature_dir,
        )

    def update_sta_data_config(self,
                               db_config: str,
                               output_dir: str,
                               lib_paths: list[str],
                               sdc_path: str):
        self.ecc.db_init(
            config_path=db_config,
            output_path=output_dir,
            lib_paths=lib_paths,
            sdc_path=sdc_path,
        )
        
    ########################################################################
    # data api
    ########################################################################
    def idb_init(self, config_path: str):
        return self.ecc.idb_init(config_path)

    def set_net(self, 
                net_name: str, 
                net_type: str):
        """
        set net type
        """
        return self.ecc.set_net(net_name=net_name, net_type=net_type)
    
    def remove_except_pg_net(self):
        return self.ecc.remove_except_pg_net()

    def clear_blockage(self, type: str):
        return self.ecc.clear_blockage(type=type)

    def idb_get(
        self,
        inst_name: str = "",
        net_name: str = "",
        file_name: str = "",
    ):
        return self.ecc.idb_get(
            inst_name=inst_name,
            net_name=net_name,
            file_name=file_name,
        )

    def delete_inst(self, inst_name: str):
        return self.ecc.delete_inst(inst_name=inst_name)

    def delete_net(self, net_name: str):
        return self.ecc.delete_net(net_name=net_name)

    def create_inst(
        self,
        inst_name: str,
        cell_master: str,
        coord_x: int = 0,
        coord_y: int = 0,
        orient: str = "",
        type: str = "",
        status: str = "",
    ):
        return self.ecc.create_inst(
            inst_name=inst_name,
            cell_master=cell_master,
            coord_x=coord_x,
            coord_y=coord_y,
            orient=orient,
            type=type,
            status=status,
        )

    def create_net(self, net_name: str, conn_type: str = ""):
        return self.ecc.create_net(net_name=net_name, conn_type=conn_type)

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

    def gds_save(self, output_path: str, is_harden: bool = False):
        """save gds file"""
        self.ecc.gds_save(output_path, is_harden)

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
        
    def json_save(self,
                  path : str):
        self.ecc.json_save(path=path)

    def view_json_save(self, output_dir: str):
        return self.ecc.view_json_save(output_dir=output_dir)

    def view_json_apply_edits(self, edits_path: str):
        return self.ecc.view_json_apply_edits(edits_path=edits_path)

    def save_data(self, path: str):
        """save ECC data"""
        return self.ecc.save_data(path=path)

    def load_data(self, path: str):
        """load ECC data"""
        return self.ecc.load_data(path=path)
    
    def is_db_data_exists(self, db_path: str) -> bool:
        if not db_path or not os.path.isdir(db_path):
            return False
    
        DB_DATA_FILES = (
            "layout/metadata.idb",
            "layout/units.idb",
            "layout/die.idb",
            "layout/layers.idb",
            "layout/sites.idb",
            "layout/rows.idb",
            "layout/gcell_grid.idb",
            "layout/track_grid.idb",
            "layout/cell_masters.idb",
            "layout/via_rules.idb",
            "layout/vias.idb",
            "design/metadata.idb",
            "design/instances.idb",
            "design/io_pins.idb",
            "design/vias.idb",
            "design/nets.idb",
            "design/special_nets.idb",
            "design/blockages.idb",
            "design/regions.idb",
            "design/slots.idb",
            "design/groups.idb",
            "design/fills.idb",
        )
        
        return all(
            os.path.isfile(os.path.join(db_path, file_path))
            for file_path in DB_DATA_FILES
        )

    def write_soc_json(self, path: str, harden_cores: list[str] | None = None):
        """write SoC json"""
        if harden_cores is None:
            harden_cores = []
        return self.ecc.write_soc_json(path=path, harden_cores=harden_cores)
    
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

    def feature_eval_map(self, path: str, bin_cnt_x: int, bin_cnt_y: int):
        return self.ecc.feature_eval_map(
            path=path,
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
        )

    def feature_eval_summary(self, path: str, grid_size: int):
        return self.ecc.feature_eval_summary(path=path, grid_size=grid_size)

    def feature_timing_eval_summary(self, path: str):
        return self.ecc.feature_timing_eval_summary(path=path)

    def feature_net_eval(self, path: str):
        return self.ecc.feature_net_eval(path=path)

    def feature_cong_map(self, step: str, dir: str):
        return self.ecc.feature_cong_map(step=step, dir=dir)
        
    ########################################################################
    # reports api
    ########################################################################
    def report_wirelength(self, path: str = ""):
        return self.ecc.report_wirelength(path=path)

    def report_summary(self, 
                       path: str):
        """
        generate step report
        """
        self.ecc.report_db(path)

    def report_congestion(self, path: str = ""):
        return self.ecc.report_congestion(path=path)

    def report_dangling_net(self, path: str = ""):
        return self.ecc.report_dangling_net(path=path)

    def report_route(
        self,
        path: str = "",
        net: str = "",
        summary: bool = True,
    ):
        return self.ecc.report_route(path=path, net=net, summary=summary)

    def report_place_distribution(self, prefixes: list[str] = []):
        return self.ecc.report_place_distribution(prefixes=prefixes)

    def report_prefixed_instance(
        self,
        prefix: str,
        level: int = 1,
        num_threshold: int = 1,
    ):
        return self.ecc.report_prefixed_instance(
            prefix=prefix,
            level=level,
            num_threshold=num_threshold,
        )

    def report_drc(self, path: str):
        return self.ecc.report_drc(path=path)

    ########################################################################
    # power api
    ########################################################################
    def read_vcd_cpp(self, file_name: str, top_name: str):
        return self.ecc.read_vcd_cpp(file_name=file_name, top_name=top_name)

    def read_pg_spef(self, pg_spef_file: str):
        return self.ecc.read_pg_spef(pg_spef_file=pg_spef_file)

    def report_power_cpp(self):
        return self.ecc.report_power_cpp()

    def report_power(self):
        return self.ecc.report_power()

    def report_ir_drop(self, power_nets: list[str]):
        return self.ecc.report_ir_drop(power_nets=power_nets)

    def get_wire_timing_power_data(self, n_worst_path_per_clock: int):
        return self.ecc.get_wire_timing_power_data(n_worst_path_per_clock)
        
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

    def place_port(
        self,
        pin_name: str,
        offset_x: int,
        offset_y: int,
        width: int,
        height: int,
        layer: str,
    ):
        return self.ecc.place_port(
            pin_name=pin_name,
            offset_x=offset_x,
            offset_y=offset_y,
            width=width,
            height=height,
            layer=layer,
        )

    def place_io_filler(
        self,
        filler_types: list[str],
        prefix: str = "IOFill",
    ):
        return self.ecc.place_io_filler(
            filler_types=filler_types,
            prefix=prefix,
        )

    def add_placement_blockage(self, box: str):
        return self.ecc.add_placement_blockage(box=box)

    def add_placement_halo(self, inst_name: str, distance: str):
        return self.ecc.add_placement_halo(
            inst_name=inst_name,
            distance=distance,
        )

    def add_routing_blockage(self, layer: str, box: str, exceptpgnet: bool):
        return self.ecc.add_routing_blockage(
            layer=layer,
            box=box,
            exceptpgnet=exceptpgnet,
        )

    def add_routing_halo(
        self,
        layer: str,
        distance: str,
        exceptpgnet: bool = False,
        *,
        inst_name: str,
    ):
        return self.ecc.add_routing_halo(
            layer=layer,
            distance=distance,
            exceptpgnet=exceptpgnet,
            inst_name=inst_name,
        )

    def place_instance(
        self,
        inst_name: str,
        llx: int,
        lly: int,
        orient: str,
        cellmaster: str,
        source: str = "",
    ):
        return self.ecc.place_instance(
            inst_name=inst_name,
            llx=llx,
            lly=lly,
            orient=orient,
            cellmaster=cellmaster,
            source=source,
        )

    ########################################################################
    # pdn api
    ########################################################################
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

    def place_pdn_port(
        self,
        pin_name: str,
        io_cell_name: str,
        offset_x: int,
        offset_y: int,
        width: int,
        height: int,
        layer: str,
    ):
        return self.ecc.place_pdn_port(
            pin_name=pin_name,
            io_cell_name=io_cell_name,
            offset_x=offset_x,
            offset_y=offset_y,
            width=width,
            height=height,
            layer=layer,
        )

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

    def connectMacroPdn(
        self,
        pin_layer: str,
        pdn_layer: str,
        power_pins: list[str],
        ground_pins: list[str],
        orient: str,
    ):
        return self.ecc.connectMacroPdn(
            pin_layer=pin_layer,
            pdn_layer=pdn_layer,
            power_pins=power_pins,
            ground_pins=ground_pins,
            orient=orient,
        )

    def connectIoPinToPower(self, point_list: list[float], layer: str):
        return self.ecc.connectIoPinToPower(
            point_list=point_list,
            layer=layer,
        )

    def connectPowerStripe(
        self,
        point_list: list[float],
        net_name: str,
        layer: str,
        width: int = -1,
    ):
        return self.ecc.connectPowerStripe(
            point_list=point_list,
            net_name=net_name,
            layer=layer,
            width=width,
        )

    def add_segment_stripe(
        self,
        net_name: str = "",
        point_list: list[float] = [],
        layer: str = "",
        width: int = 0,
        point_begin: list[float] = [],
        layer_start: str = "",
        point_end: list[float] = [],
        layer_end: str = "",
        via_width: int = 0,
        via_height: int = 0,
    ):
        return self.ecc.add_segment_stripe(
            net_name=net_name,
            point_list=point_list,
            layer=layer,
            width=width,
            point_begin=point_begin,
            layer_start=layer_start,
            point_end=point_end,
            layer_end=layer_end,
            via_width=via_width,
            via_height=via_height,
        )

    def add_segment_via(
        self,
        net_name: str,
        layer: str = "",
        top_layer: str = "",
        bottom_layer: str = "",
        *,
        offset_x: int,
        offset_y: int,
        width: int,
        height: int,
    ):
        return self.ecc.add_segment_via(
            net_name=net_name,
            layer=layer,
            top_layer=top_layer,
            bottom_layer=bottom_layer,
            offset_x=offset_x,
            offset_y=offset_y,
            width=width,
            height=height,
        )

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
    # pnp api
    ########################################################################
    def pnp(self, config: str):
        self.ecc.run_pnp(config)
    
    ########################################################################
    # placement api
    ########################################################################
    def run_placement(self, config: str):
        self.ecc.run_placer(config)

    def init_pl(self, config: str):
        return self.ecc.init_pl(config=config)

    def destroy_pl(self):
        return self.ecc.destroy_pl()
        
    def feature_placement_map(self, json_path: str, map_grid_size=1):
        """
        generate placement map feature
        """
        self.ecc.feature_pl_eval(json_path, map_grid_size)

    def run_incremental_flow(self, config: str):
        return self.ecc.run_incremental_flow(config=config)

    def run_legalize(self, config: str):
        self.ecc.run_incremental_lg()
        
    def run_filler(self, config: str):
        self.ecc.insert_filler(config)
        
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

    def placer_run_mp(self):
        return self.ecc.placer_run_mp()

    def placer_run_gp(self):
        return self.ecc.placer_run_gp()

    def placer_run_lg(self):
        return self.ecc.placer_run_lg()

    def placer_run_dp(self):
        return self.ecc.placer_run_dp()
        
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
    def run_ert(self, config: str = "", config_dict: dict[str, str] = {}):
        return self.ecc.run_ert(config=config, config_dict=config_dict)

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
    # RCX api
    ########################################################################
    def init_rcx(self, config: str, pdk: str = "ics55"):
        if pdk:
            return self.ecc.init_rcx(config=config, pdk=pdk)
        return self.ecc.init_rcx(config=config)
    
    def run_rcx(self):
        return self.ecc.run_rcx()

    def report_rcx(self):
        return self.ecc.report_rcx()
    
    
    ########################################################################
    # STA api
    ########################################################################
    def run_sta(self, output_dir: str):
        return self.ecc.run_sta(output=output_dir)

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

    def release_sta(self):
        return self.ecc.release_sta()

    def report_sta(self, output=None):
        if output is None:
            return self.ecc.report_sta()
        return self.ecc.report_sta(output)

    def init_log(self, log_dir: str):
        return self.ecc.init_log(log_dir)

    def set_design_workspace(self, design_workspace: str):
        return self.ecc.set_design_workspace(design_workspace)

    def read_lef_def(self, lef_files: list[str], def_file: str):
        return self.ecc.read_lef_def(lef_files, def_file)

    def read_netlist(self, file_name: str):
        return self.ecc.read_netlist(file_name)
        
    def read_liberty(self, lib_paths : list[str]):
        return self.ecc.read_liberty(lib_paths)
        
    def link_design(self, design : str):
        return self.ecc.link_design(design)

    def read_spef(self, file_name: str):
        return self.ecc.read_spef(file_name)

    def read_sdc(self, sdc_path : str):
        return self.ecc.read_sdc(sdc_path)

    def get_net_name(self, pin_port_name: str):
        return self.ecc.get_net_name(pin_port_name)

    def get_segment_capacitance(
        self,
        layer_id: int,
        segment_length: double,
        route_layer_id: int,
    ):
        return self.ecc.get_segment_capacitance(
            layer_id,
            segment_length,
            route_layer_id,
        )

    def get_segment_resistance(
        self,
        layer_id: int,
        segment_length: double,
        route_layer_id: int,
    ):
        return self.ecc.get_segment_resistance(
            layer_id,
            segment_length,
            route_layer_id,
        )

    def make_rc_tree_inner_node(self, net_name: str, node_id: int, cap: float):
        return self.ecc.make_rc_tree_inner_node(net_name, node_id, cap)

    def make_rc_tree_obj_node(self, pin_port_name: str, cap: float):
        return self.ecc.make_rc_tree_obj_node(pin_port_name, cap)

    def make_rc_tree_edge(self, net_name: str, node1: str, node2: str, res: float):
        return self.ecc.make_rc_tree_edge(net_name, node1, node2, res)

    def update_rc_tree_info(self, net_name: str):
        return self.ecc.update_rc_tree_info(net_name)

    def update_timing(self):
        return self.ecc.update_timing()

    def write_abstract_lef(self, output_lef_path: str):
        return self.ecc.write_abstract_lef(output_lef_path)

    def write_timing_model(
        self,
        output_lib_path: str,
        analysis_mode: str = "max"):
        return self.ecc.write_timing_model(output_lib_path, analysis_mode)
        
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

    def build_timing_graph(self):
        return self.ecc.build_timing_graph()

    def update_clock_timing(self):
        return self.ecc.update_clock_timing()

    def convert_idb_to_timing_netlist(self):
        return self.ecc.convert_idb_to_timing_netlist()

    def get_wire_timing_data(self, n_worst_path_per_clock: int):
        return self.ecc.get_wire_timing_data(n_worst_path_per_clock)
        
    ########################################################################
    # timing opt api
    ########################################################################
    def run_to(self, config: str):
        return self.ecc.run_to(config=config)

    def run_timing_opt_drv(self, config: str):
        self.ecc.run_to_drv(config)

    def run_timing_opt_hold(self, config: str):
        self.ecc.run_to_hold(config)

    def run_timing_opt_setup(self, config: str):
        self.ecc.run_to_setup(config)
    
    ########################################################################
    # data vectorization
    ########################################################################
    def layout_patchs(self, path: str):
        return self.ecc.layout_patchs(path=path)

    def layout_graph(self, path: str):
        return self.ecc.layout_graph(path=path)

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

    def get_timing_wire_graph(self, wire_graph_path: str):
        return self.ecc.get_timing_wire_graph(wire_graph_path)

    def get_timing_instance_graph(self, instance_graph_path: str):
        return self.ecc.get_timing_instance_graph(instance_graph_path)
    
    ########################################################################
    # evaluation api
    ########################################################################
    def total_wirelength_dict(self):
        return self.ecc.total_wirelength_dict()

    def cell_density(
        self,
        bin_cnt_x: int = 256,
        bin_cnt_y: int = 256,
        save_path: str = "",
    ):
        return self.ecc.cell_density(
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
            save_path=save_path,
        )

    def pin_density(
        self,
        bin_cnt_x: int = 256,
        bin_cnt_y: int = 256,
        save_path: str = "",
    ):
        return self.ecc.pin_density(
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
            save_path=save_path,
        )

    def net_density(
        self,
        bin_cnt_x: int = 256,
        bin_cnt_y: int = 256,
        save_path: str = "",
    ):
        return self.ecc.net_density(
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
            save_path=save_path,
        )

    def rudy_congestion(
        self,
        bin_cnt_x: int = 256,
        bin_cnt_y: int = 256,
        save_path: str = "",
    ):
        return self.ecc.rudy_congestion(
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
            save_path=save_path,
        )

    def lut_rudy_congestion(
        self,
        bin_cnt_x: int = 256,
        bin_cnt_y: int = 256,
        save_path: str = "",
    ):
        return self.ecc.lut_rudy_congestion(
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
            save_path=save_path,
        )

    def egr_congestion(self, save_path: str = ""):
        return self.ecc.egr_congestion(save_path=save_path)

    def timing_power_hpwl(self):
        return self.ecc.timing_power_hpwl()

    def timing_power_stwl(self):
        return self.ecc.timing_power_stwl()

    def timing_power_egr(self):
        return self.ecc.timing_power_egr()

    def eval_macro_margin(self):
        return self.ecc.eval_macro_margin()

    def eval_continuous_white_space(self):
        return self.ecc.eval_continuous_white_space()

    def eval_macro_channel(self, die_size_ratio: float):
        return self.ecc.eval_macro_channel(die_size_ratio=die_size_ratio)

    def eval_cell_hierarchy(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_cell_hierarchy(
            plot_path=plot_path,
            level=level,
            forward=forward,
        )

    def eval_macro_hierarchy(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_hierarchy(
            plot_path=plot_path,
            level=level,
            forward=forward,
        )

    def eval_macro_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_connection(
            plot_path=plot_path,
            level=level,
            forward=forward,
        )

    def eval_macro_pin_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_pin_connection(
            plot_path=plot_path,
            level=level,
            forward=forward,
        )

    def eval_macro_io_pin_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_io_pin_connection(
            plot_path=plot_path,
            level=level,
            forward=forward,
        )

    def eval_overflow(self):
        return self.ecc.eval_overflow()
    
    ########################################################################
    # net optimization
    ########################################################################
    def run_net_opt(self, config : str):
        return self.ecc.fix_fanout(config)
    
    def build_rc_tree_from_flat_data(
        self,
        netName: str,
        node_sta_names: list[str],
        node_is_pin: list[bool],
        steiner_indices: list[int],
        parent_indices: list[int],
        node_total_caps: list[float],
        edge_resistances: list[float],
        node_global_indices: list[int],
    ):
        return self.ecc.build_rc_tree_from_flat_data(
            netName,
            node_sta_names,
            node_is_pin,
            steiner_indices,
            parent_indices,
            node_total_caps,
            edge_resistances,
            node_global_indices,
        )

    def update_and_get_all_pin_timings(
        self,
        pin_names: list[str],
        arrival_late_times,
        arrival_early_times,
        required_late_times,
        required_early_times,
        pin_net_delay,
        cell_arc_delays,
        net_timing_details,
    ):
        return self.ecc.update_and_get_all_pin_timings(
            pin_names,
            arrival_late_times,
            arrival_early_times,
            required_late_times,
            required_early_times,
            pin_net_delay,
            cell_arc_delays,
            net_timing_details,
        )
