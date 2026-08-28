#!/usr/bin/env python
import json
import os
import shutil
from pathlib import Path
from typing import TypeAlias

from chipcompiler.tools.ecc.sta_artifacts import discard_sta_run_outputs, publish_sta_artifacts
from chipcompiler.utility.path import path_text, path_texts

# ecc-tools loggers terminate the host process on error by default; embedded in
# Python they must raise instead so failures surface as Python exceptions.
os.environ.setdefault("ECC_LOGGER_THROW_ON_ERROR", "1")

# Path arguments to the native-wrapper methods are normalized via path_text(),
# so they accept a Path, a str, or None (a step group field is Path | None).
PathArg: TypeAlias = str | Path | None


STA_OUTPUT_MODES = frozenset(("report", "structured"))


def _normalize_sta_output_modes(output_modes) -> tuple[str, ...]:
    if isinstance(output_modes, str):
        output_modes = (output_modes,)
    try:
        modes = tuple(dict.fromkeys(output_modes))
    except TypeError as exc:
        raise ValueError("STA output_modes must be an iterable of mode names") from exc
    if not modes:
        raise ValueError("STA output_modes must request report, structured, or both")
    invalid_modes = set(modes) - STA_OUTPUT_MODES
    if invalid_modes:
        raise ValueError(f"Unsupported STA output modes: {sorted(invalid_modes)}")
    return modes


class ECCToolsModule:
    """
    python api package of ECC.
    """

    def __init__(self):
        try:
            from ecc_tools_bin import ecc_py as ecc
        except ImportError as exc:
            ecc_bin_dir = Path(__file__).resolve().parent / "bin"
            candidates = sorted(p.name for p in ecc_bin_dir.glob("ecc_py*.so"))
            raise ImportError(
                "ecc-tools is not installed. Install the ecc-tools wheel or "
                "build from source "
                f"Import error: {exc}. "
                f"Available ecc_py binaries in {ecc_bin_dir}: {candidates}"
            ) from exc

        self.ecc = ecc

    def get_ecc(self):
        return self.ecc

    def exit(self):
        """exit ECC tools"""
        self.ecc.flow_exit()

    def close(self):
        """release ECC data without terminating the host process"""
        self.reset_data()

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
    def init_config(self, db_config: str, output_dir: PathArg, feature_dir: PathArg):
        """init_config"""
        self.ecc.db_init(
            config_path=path_text(db_config),
            output_path=path_text(output_dir),
            feature_path=path_text(feature_dir),
        )

    def update_step_paths(self, output_dir: PathArg, feature_dir: PathArg):
        self.ecc.db_init(
            output_path=path_text(output_dir),
            feature_path=path_text(feature_dir),
        )

    def update_sta_data_config(
        self, db_config: str, output_dir: str, lib_paths: list[str], sdc_path: str
    ):
        self.ecc.db_init(
            config_path=path_text(db_config),
            output_path=path_text(output_dir),
            lib_paths=path_texts(lib_paths),
            sdc_path=path_text(sdc_path),
        )

    ########################################################################
    # data api
    ########################################################################
    def idb_init(self, config_path: str):
        return self.ecc.idb_init(path_text(config_path))

    def set_net(self, net_name: str, net_type: str):
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

    def place_instance(
        self,
        inst_name: str,
        llx: int,
        lly: int,
        orient: str,
        cellmaster: str,
        source: str = "",
        placement_status: str = "fixed",
        *,
        create_if_missing: bool = True,
    ):
        params = {
            "inst_name": inst_name,
            "llx": llx,
            "lly": lly,
            "orient": orient,
            "cellmaster": cellmaster,
            "source": source,
        }
        if placement_status != "fixed" or not create_if_missing:
            params["placement_status"] = placement_status
            params["create_if_missing"] = create_if_missing
        return self.ecc.place_instance(**params)

    def set_exclude_cell_names(self, cell_names: set):
        self.cell_names = cell_names

    def write_placement_back(self, dm_inst_ptr, node_x, node_y):
        self.ecc.write_placement_back(dm_inst_ptr, node_x, node_y)

    ########################################################################
    # data io api
    ########################################################################
    def init_techlef(self, tech_lef_path: str):
        """init tech lef"""
        self.ecc.tech_lef_init(path_text(tech_lef_path))

    def init_lefs(self, lef_paths: list):
        """init_lef"""
        self.ecc.lef_init(lef_paths=path_texts(lef_paths))

    def read_def(self, path: str = "") -> bool:
        """init def"""
        return self.ecc.def_init(def_path=path_text(path))

    def read_verilog(self, verilog: PathArg, top_module: str):
        """init verilog"""
        self.ecc.verilog_init(path_text(verilog), top_module)

    def read_lvs_verilog(self, verilog: PathArg, top_module: str) -> bool:
        """init verilog for iLVS"""
        return self.ecc.lvs_verilog_init(path_text(verilog), top_module)

    def def_save(self, def_path: PathArg):
        """save def file"""
        self.ecc.def_save(def_name=path_text(def_path))

    def gds_save(self, output_path: PathArg, *, is_harden: bool = False):
        """save gds file"""
        self.ecc.gds_save(path_text(output_path), is_harden)

    def tcl_save(self, output_path: str):
        """save tcl file"""
        self.ecc.tcl_save(path_text(output_path))

    def verilog_save(self, output_verilog, cell_names: set | None = None):
        """verilog save"""
        if cell_names is None:
            cell_names = set()
        self.ecc.netlist_save(netlist_path=path_text(output_verilog), exclude_cell_names=cell_names)

    def json_save(self, path: str):
        self.ecc.json_save(path=path_text(path))

    def view_json_save(
        self,
        output_dir: PathArg,
        json_format: str = "pretty",
        *,
        compress: bool = False,
    ):
        """
        Export the current iDB design as a view JSON package.

        Args:
            output_dir: Directory used to write manifest.json and package files.
            json_format: JSON text layout. Use "pretty" for indented output or
                "compact" to remove extra spaces/newlines and reduce file size.
            compress: When True, write package JSON files as .json.gz. The
                manifest.json entry file remains plain JSON and points to the
                compressed package files.
        """
        return self.ecc.view_json_save(
            output_dir=path_text(output_dir),
            json_format=json_format,
            compress=compress,
        )

    def view_json_apply_edits(self, edits_path: PathArg, *, compress: bool = False):
        """
        Apply edits generated for a view JSON package.

        Args:
            edits_path: Path to layout_edits.json or layout_edits.json.gz.
            compress: When True, prefer reading edits_path + ".gz" if edits_path
                does not already end with ".gz".
        """
        return self.ecc.view_json_apply_edits(edits_path=path_text(edits_path), compress=compress)

    def geometry_snapshot_save(self, output_dir: PathArg):
        """Export the current in-memory IDB geometry for GUI rendering."""
        return self.ecc.geometry_snapshot_save(output_dir=path_text(output_dir))

    def initialize_geometry_session(self):
        """Begin a geometry edit session for incremental GUI updates."""
        return self.ecc.initialize_geometry_session()

    def sync_instance_geometry(self, inst_name: str):
        """Synchronize one edited instance from IDB into the geometry session."""
        return self.ecc.sync_instance_geometry(inst_name=inst_name)

    def geometry_session_snapshot_save(self, output_dir: PathArg):
        """Export the incremental geometry-session snapshot for GUI rendering."""
        return self.ecc.geometry_session_snapshot_save(output_dir=path_text(output_dir))

    def reset_geometry_session(self):
        """Discard the active geometry edit session."""
        return self.ecc.reset_geometry_session()

    def save_data(self, path: PathArg):
        """save ECC data"""
        return self.ecc.save_data(path=path_text(path))

    def load_data(self, path: str | Path):
        """load ECC data"""
        return self.ecc.load_data(path=path_text(path))

    def is_db_data_exists(self, db_path: str | Path) -> bool:
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

        return all(os.path.isfile(os.path.join(db_path, file_path)) for file_path in DB_DATA_FILES)

    def write_soc_json(self, path: str, harden_cores: list[str] | None = None):
        """write SoC json"""
        if harden_cores is None:
            harden_cores = []
        return self.ecc.write_soc_json(path=path_text(path), harden_cores=harden_cores)

    ########################################################################
    # feature api
    ########################################################################
    def feature_sammry(self, json_path: PathArg):
        """
        generate feature summary
        """
        self.ecc.feature_summary(path_text(json_path))

    def feature_step(self, step: str, json_path: PathArg):
        """
        generate step feature
        """
        self.ecc.feature_tool(path_text(json_path), step)

    def feature_eval_map(self, path: str, bin_cnt_x: int, bin_cnt_y: int):
        return self.ecc.feature_eval_map(
            path=path_text(path),
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
        )

    def feature_eval_summary(self, path: str, grid_size: int):
        return self.ecc.feature_eval_summary(path=path_text(path), grid_size=grid_size)

    def feature_timing_eval_summary(self, path: str):
        return self.ecc.feature_timing_eval_summary(path=path_text(path))

    def feature_net_eval(self, path: str):
        return self.ecc.feature_net_eval(path=path_text(path))

    def feature_cong_map(self, step: str, dir: str):
        return self.ecc.feature_cong_map(step=step, dir=path_text(dir))

    ########################################################################
    # reports api
    ########################################################################
    def report_wirelength(self, path: str = ""):
        return self.ecc.report_wirelength(path=path_text(path))

    def report_summary(self, path: PathArg):
        """
        generate step report
        """
        self.ecc.report_db(path_text(path))

    def report_congestion(self, path: str = ""):
        return self.ecc.report_congestion(path=path_text(path))

    def report_dangling_net(self, path: str = ""):
        return self.ecc.report_dangling_net(path=path_text(path))

    def report_route(
        self,
        path: str = "",
        net: str = "",
        *,
        summary: bool = True,
    ):
        return self.ecc.report_route(path=path_text(path), net=net, summary=summary)

    def report_place_distribution(self, prefixes: list[str] | None = None):
        if prefixes is None:
            prefixes = []
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
        return self.ecc.report_drc(path=path_text(path))

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
    def run_cts(self, config: str, output: PathArg) -> bool:
        return self.ecc.run_cts(path_text(config), path_text(output))

    def report_cts(self, output: PathArg):
        self.ecc.cts_report(path_text(output))

    def feature_cts_timing(self) -> dict:
        """Return post-optimization CTS FastSTA timing aggregates."""
        return self.ecc.cts_timing_feature()

    def feature_cts_map(self, json_path: PathArg, map_grid_size=5):
        """
        generate cts map feature
        """
        self.ecc.feature_cts_eval(path_text(json_path), map_grid_size)

    ########################################################################
    # DRC api
    ########################################################################
    def init_drc(self, output_dir: PathArg, therad_number: int = 128):
        """
        init drc config
        """
        self.ecc.init_drc(temp_directory_path=path_text(output_dir), thread_number=therad_number)

    def run_drc(self, config: str, report_path: PathArg = "") -> bool:
        """
        run drc check
        """
        self.ecc.run_drc(config=path_text(config), report=path_text(report_path))

    def save_drc(self, feature_path: PathArg):
        """
        generate drc result
        """
        self.ecc.save_drc(path=path_text(feature_path))

    ########################################################################
    # LVS api
    ########################################################################
    def init_lvs(self, output_dir: PathArg, thread_number: int = 128):
        return self.ecc.init_lvs(
            temp_directory_path=path_text(output_dir),
            thread_number=thread_number,
        )

    def run_lvs(self):
        return self.ecc.run_lvs()

    def destroy_lvs(self):
        return self.ecc.destroy_lvs()

    ########################################################################
    # floorplan api
    ########################################################################
    def init_fp(self, config: str):
        return self.ecc.init_fp(config=path_text(config))

    def run_fp(self):
        return self.ecc.run_fp()

    def destroy_fp(self):
        return self.ecc.destroy_fp()

    ########################################################################
    # pnp api
    ########################################################################
    def pnp(self, config: str):
        self.ecc.run_pnp(path_text(config))

    ########################################################################
    # placement api
    ########################################################################
    def feature_placement_map(self, json_path: PathArg, map_grid_size=5):
        """
        generate placement map feature
        """
        self.ecc.feature_pl_eval(path_text(json_path), map_grid_size)

    def run_filler(self, config: str):
        self.ecc.insert_filler(path_text(config))

    ########################################################################
    # routing api
    ########################################################################
    def run_ert(self, config: str = "", config_dict: dict[str, str] | None = None):
        if config_dict is None:
            config_dict = {}
        return self.ecc.run_ert(config=path_text(config), config_dict=config_dict)

    def run_routing(self, config: str):
        self.ecc.init_rt(config=path_text(config))
        self.ecc.run_rt()
        self.ecc.destroy_rt()

    def close_routing(self):
        self.ecc.destroy_rt()

    # read route json file to ecc route data
    def feature_route_read(self, json_path: str):
        self.ecc.feature_route_read(path=path_text(json_path))

    # read route def and save route data to json
    def feature_route(self, json_path: str):
        self.ecc.feature_route(path=path_text(json_path))

    def is_rt_timing_enable(self, config: str):
        if os.path.exists(config):
            with open(config, encoding="utf-8") as f_reader:
                json_data = json.load(f_reader)
                # check if time enable
                if (
                    json_data is not None
                    and json_data.get("RT", {}).get("-enable_timing", "0") == "1"
                ):
                    return True
        return False

    ########################################################################
    # RCX api
    ########################################################################
    def init_rcx(self, config: str, pdk: str = "ics55"):
        if pdk:
            return self.ecc.init_rcx(config=path_text(config), pdk=pdk)
        return self.ecc.init_rcx(config=path_text(config))

    def run_rcx(self):
        return self.ecc.run_rcx()

    def destroy_rcx(self):
        destroy_rcx = getattr(self.ecc, "destroy_rcx", None)
        if destroy_rcx is None:
            return None
        return destroy_rcx()

    ########################################################################
    # STA api
    ########################################################################
    def run_timing(
        self,
        config: str = "",
        work_dir: PathArg = "",
        report_dir: PathArg = "",
        feature_dir: PathArg = "",
        lib_paths: list[Path] | list[str] | None = None,
        sdc_path: str = "",
        spef_path: str = "",
        output_modes: tuple[str, ...] = ("report", "structured"),
        max_paths_per_analysis: int = 20,
        max_paths: int = 1000,
        corner: str = "",
    ):
        if lib_paths is None:
            lib_paths = []
        modes = _normalize_sta_output_modes(output_modes)
        if not work_dir:
            raise ValueError("STA work_dir is required for artifact collection")
        if (
            isinstance(max_paths_per_analysis, bool)
            or not isinstance(max_paths_per_analysis, int)
            or max_paths_per_analysis <= 0
        ):
            raise ValueError("STA max_paths_per_analysis must be a positive integer")
        if isinstance(max_paths, bool) or not isinstance(max_paths, int) or max_paths <= 0:
            raise ValueError("STA max_paths must be a positive integer")
        if "report" in modes and not report_dir:
            raise ValueError("STA report_dir is required when report output is requested")
        if "structured" in modes and not feature_dir:
            raise ValueError("STA feature_dir is required when structured output is requested")

        discard_sta_run_outputs(work_dir, report_dir, feature_dir, modes)

        self.ecc.lib_init(lib_paths=path_texts(lib_paths))
        self.ecc.sdc_init(path_text(sdc_path))
        self.ecc.spef_init(path_text(spef_path))
        config_dict = {}
        if work_dir:
            config_dict["-temp_directory_path"] = path_text(work_dir)
        config_dict.update(
            {
                "-output_timing_reports": "1" if "report" in modes else "0",
                "-output_timing_features": "1" if "structured" in modes else "0",
                "-timing_path_limit": str(max_paths_per_analysis),
                "-max_paths": str(max_paths),
            }
        )
        if corner:
            config_dict["-timing_corner"] = corner
        self.ecc.init_sta(config=path_text(config), config_dict=config_dict)
        try:
            self.ecc.run_sta()
        finally:
            self.ecc.destroy_sta()

        publish_sta_artifacts(
            work_dir=work_dir or "",
            report_dir=report_dir or "",
            feature_dir=feature_dir or "",
            modes=modes,
        )

    def write_abstract_lef(self, output_lef_path: PathArg):
        return self.ecc.write_abstract_lef(path_text(output_lef_path))

    def write_timing_model(
        self,
        output_lib_path: PathArg,
        analysis_mode: str = "max",
        config: str = "",
        output_dir: PathArg = "",
        lib_paths: list[str] | None = None,
        sdc_path: str = "",
        spef_path: str = "",
        design_name: str = "",
    ):
        output_lib_path = Path(output_lib_path or "")
        output_lib_path.parent.mkdir(parents=True, exist_ok=True)

        if lib_paths is None:
            lib_paths = []

        analysis_mode = analysis_mode.lower()
        if not design_name:
            design_name = output_lib_path.stem
            if design_name.endswith("_Harden"):
                design_name = design_name[: -len("_Harden")]

        sta_output_dir = Path(output_dir) if output_dir else output_lib_path.parent
        self.ecc.lib_init(lib_paths=path_texts(lib_paths))
        self.ecc.sdc_init(path_text(sdc_path))
        self.ecc.spef_init(path_text(spef_path))
        config_dict = {"-temp_directory_path": path_text(sta_output_dir)}
        self.ecc.init_sta(config=path_text(config), config_dict=config_dict)
        try:
            self.ecc.extract_lib()
        finally:
            self.ecc.destroy_sta()

        source_lib_path = (
            sta_output_dir / "timing_characterizer" / f"{design_name}_{analysis_mode}.lib"
        )
        if not source_lib_path.exists():
            candidates = sorted(
                (sta_output_dir / "timing_characterizer").glob(f"*_{analysis_mode}.lib")
            )
            if len(candidates) == 1:
                source_lib_path = candidates[0]
            else:
                raise FileNotFoundError(source_lib_path)

        if source_lib_path.resolve() != output_lib_path.resolve():
            shutil.copyfile(source_lib_path, output_lib_path)

        if output_lib_path.stat().st_size <= 0:
            output_lib_path.write_text(
                f"library ({design_name}_{analysis_mode}) {{\n"
                f"  cell ({design_name}) {{\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )

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
            save_path=path_text(save_path),
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
            save_path=path_text(save_path),
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
            save_path=path_text(save_path),
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
            save_path=path_text(save_path),
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
            save_path=path_text(save_path),
        )

    def egr_congestion(self, save_path: str = ""):
        return self.ecc.egr_congestion(save_path=path_text(save_path))

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
            plot_path=path_text(plot_path),
            level=level,
            forward=forward,
        )

    def eval_macro_hierarchy(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_hierarchy(
            plot_path=path_text(plot_path),
            level=level,
            forward=forward,
        )

    def eval_macro_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_connection(
            plot_path=path_text(plot_path),
            level=level,
            forward=forward,
        )

    def eval_macro_pin_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_pin_connection(
            plot_path=path_text(plot_path),
            level=level,
            forward=forward,
        )

    def eval_macro_io_pin_connection(self, plot_path: str, level: int, forward: int):
        return self.ecc.eval_macro_io_pin_connection(
            plot_path=path_text(plot_path),
            level=level,
            forward=forward,
        )

    def eval_overflow(self):
        return self.ecc.eval_overflow()

    ########################################################################
    # net optimization
    ########################################################################
    def run_net_opt(self, config: str):
        return self.ecc.fix_fanout(path_text(config))

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
