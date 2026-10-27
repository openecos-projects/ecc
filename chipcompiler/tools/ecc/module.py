#!/usr/bin/env python
import importlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from chipcompiler.tools.ecc.sta_artifacts import discard_sta_run_outputs, publish_sta_artifacts
from chipcompiler.utility.path import PathArg, path_list, path_text

# ecc-tools loggers terminate the host process on error by default; embedded in
# Python they must raise instead so failures surface as Python exceptions.
os.environ.setdefault("ECC_LOGGER_THROW_ON_ERROR", "1")

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


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _place_timing_kwargs(inputs: dict[str, object]) -> dict[str, Any]:
    """Map a placement-timing input record onto _start_place_timing's keywords.

    The record comes from DreamPlace and is untyped, so path-like values are
    read as-is; missing or empty entries become "" (the native "unset" value).
    """

    def first(*keys: str) -> Any:
        for key in keys:
            if inputs.get(key):
                return inputs[key]
        return ""

    return {
        "lib_paths": list(first("lib_paths", "lib") or []),
        "sdc_path": first("sdc_path", "sdc"),
        "spef_path": first("spef_path", "spef"),
        "rcx_config": first("rcx_config"),
        "rcx_pdk": str(first("rcx_pdk")),
        "rcx_output_dir": first("rcx_output_dir"),
        "rcx_spef_path": first("rcx_spef_path"),
        "config": first("config", "sta_config"),
        "work_dir": first("work_dir"),
        "thread_number": _positive_int(inputs.get("thread_number"), 2),
        "max_paths": _positive_int(inputs.get("max_paths"), 20),
        "timing_mode": str(first("timing_mode", "preparation_mode") or "model_only"),
    }


class ECCToolsModule:
    """
    python api package of ECC.
    """

    def __init__(self):
        try:
            ecc = importlib.import_module("ecc_tools_bin.ecc_py")
        except ImportError as exc:
            ecc_bin_dir = Path(__file__).resolve().parent / "bin"
            candidates = sorted(p.name for p in ecc_bin_dir.glob("ecc_py*.so"))
            raise ImportError(
                "ecc-tools is not installed. Install the ecc-tools wheel or "
                "build from source "
                f"Import error: {exc}. "
                f"Available ecc_py binaries in {ecc_bin_dir}: {candidates}"
            ) from exc

        self.ecc: Any = ecc
        self.dir_workspace = ""
        self._place_timing_active = False
        self._place_timing_inputs = None

    def get_ecc(self):
        return self.ecc

    def exit(self):
        """exit ECC tools"""
        self.ecc.flow_exit()

    def close(self):
        """release ECC data without terminating the host process"""
        if getattr(self, "_place_timing_active", False):
            self.destroy_place_timing()
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
        include_m2_pg_rail_blockage: bool = False,  # noqa: FBT001, FBT002
        include_m2_pg_rail_density: bool = True,  # noqa: FBT001, FBT002
        timing_model_only: bool = False,  # noqa: FBT001, FBT002
    ):
        return self.ecc.pydb(
            dm_inst_ptr,
            route_num_bins_x,
            route_num_bins_y,
            routability_opt_flag,
            with_sta,
            include_m2_pg_rail_blockage,
            include_m2_pg_rail_density,
            timing_model_only,
        )

    def _place_timing_config(
        self,
        *,
        config: PathArg = "",
        work_dir: PathArg = "",
        thread_number: int = 2,
        max_paths: int = 20,
    ) -> dict[str, str]:
        if isinstance(thread_number, bool) or int(thread_number) <= 0:
            raise ValueError("placement timing thread_number must be positive")
        if isinstance(max_paths, bool) or int(max_paths) <= 0:
            raise ValueError("placement timing max_paths must be positive")
        config_dict = {
            "-output_timing_reports": "0",
            "-output_timing_features": "0",
            "-timing_path_limit": str(int(max_paths)),
            "-max_paths": str(int(max_paths)),
            "-thread_number": str(int(thread_number)),
        }
        if work_dir:
            config_dict["-temp_directory_path"] = os.fspath(work_dir)
        return {"config": os.fspath(config), **config_dict}

    def _start_place_timing(
        self,
        *,
        lib_paths: list[Path] | list[str],
        sdc_path: PathArg,
        spef_path: PathArg = "",
        rcx_config: PathArg = "",
        rcx_pdk: str = "",
        rcx_output_dir: PathArg = "",
        rcx_spef_path: PathArg = "",
        config: PathArg = "",
        work_dir: PathArg = "",
        thread_number: int = 2,
        max_paths: int = 20,
        timing_mode: str = "model_only",
    ) -> dict[str, object]:
        normalized_libs = [os.fspath(path) for path in lib_paths if path]
        normalized_sdc = os.fspath(sdc_path)
        normalized_spef = os.fspath(spef_path)
        if not normalized_libs:
            raise ValueError("ECC placement timing requires at least one Liberty")
        if not normalized_sdc:
            raise ValueError("ECC placement timing requires an SDC path")

        if self.ecc.lib_init(lib_paths=normalized_libs) is not True:
            raise RuntimeError("ECC placement timing Liberty initialization failed")
        if self.ecc.sdc_init(normalized_sdc) is not True:
            raise RuntimeError("ECC placement timing SDC initialization failed")
        normalized_rcx = os.fspath(rcx_config)
        normalized_rcx_output = os.fspath(rcx_output_dir)
        if normalized_rcx:
            normalized_spef, rcx_summary = self._extract_place_parasitics(
                normalized_rcx,
                pdk=rcx_pdk,
                output_dir=normalized_rcx_output,
                requested_spef=os.fspath(rcx_spef_path) or normalized_spef,
            )
        else:
            rcx_summary = {
                "status": "skipped",
                "reason": "no_rcx_config",
            }
        if normalized_spef and self.ecc.spef_init(normalized_spef) is not True:
            raise RuntimeError("ECC placement timing SPEF initialization failed")
        config_dict = self._place_timing_config(
            config=config,
            work_dir=work_dir,
            thread_number=thread_number,
            max_paths=max_paths,
        )
        sta_config = config_dict.pop("config")
        if self.ecc.init_sta(config=sta_config, config_dict=config_dict) is not True:
            raise RuntimeError("ECC placement timing STA initialization failed")
        if timing_mode not in {"complete", "model_only"}:
            raise ValueError("timing_mode must be complete or model_only")
        try:
            operation = (
                self.ecc.run_sta if timing_mode == "complete" else self.ecc.prepare_timing_model
            )
            if operation() is not True:
                raise RuntimeError(
                    "ECC placement timing "
                    + ("STA execution" if timing_mode == "complete" else "model preparation")
                    + " failed"
                )
        except Exception:
            self.ecc.destroy_sta()
            raise
        self._place_timing_active = True
        self._place_timing_inputs = {
            "lib_paths": normalized_libs,
            "sdc_path": normalized_sdc,
            "spef_path": normalized_spef,
            "rcx_config": normalized_rcx,
            "rcx_pdk": rcx_pdk,
            "rcx_output_dir": normalized_rcx_output,
            "rcx_spef_path": normalized_spef if normalized_rcx else "",
            "config": sta_config,
            "work_dir": os.fspath(work_dir),
            "thread_number": int(thread_number),
            "max_paths": int(max_paths),
            "timing_mode": timing_mode,
        }
        return {
            "status": "ok",
            "mode": timing_mode,
            "lib_count": len(normalized_libs),
            "sdc_path": normalized_sdc,
            "spef_path": normalized_spef,
            "parasitics_initialization": (
                "rcx" if normalized_rcx else ("spef" if normalized_spef else "none")
            ),
            "rcx": rcx_summary,
        }

    def _extract_place_parasitics(
        self,
        config: PathArg,
        *,
        pdk: str = "",
        output_dir: PathArg = "",
        requested_spef: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Run the configured native RCX backend and select its fresh SPEF."""
        if self.init_rcx(config=config, pdk=pdk) is not True:
            raise RuntimeError("ECC placement timing RCX initialization failed")
        try:
            if self.run_rcx() is not True:
                raise RuntimeError("ECC placement timing RCX execution failed")
        finally:
            self.destroy_rcx()

        output_path = Path(output_dir) if output_dir else None
        if output_path is None:
            with open(config, encoding="utf-8") as stream:
                config_payload = json.load(stream)
            configured_output = config_payload.get("output")
            if not configured_output:
                raise ValueError("ECC placement timing RCX config has no output")
            output_path = Path(configured_output)
            if not output_path.is_absolute():
                output_path = Path(config).resolve().parent / output_path
        spef_dir = output_path / "spef_writer"
        candidates = sorted(spef_dir.glob("*.spef"))
        selected = None
        if requested_spef:
            requested_name = Path(requested_spef).name
            matching = [candidate for candidate in candidates if candidate.name == requested_name]
            if matching:
                selected = matching[0]
        elif len(candidates) == 1:
            selected = candidates[0]
        elif candidates:
            raise ValueError(
                "ECC placement timing RCX produced multiple SPEFs; provide rcx_spef_path"
            )
        if selected is None or not selected.is_file() or selected.stat().st_size == 0:
            raise FileNotFoundError(
                f"ECC placement timing RCX produced no usable SPEF in {spef_dir}"
            )
        return str(selected), {
            "status": "ok",
            "backend": "native_rcx",
            "output_dir": str(output_path),
            "spef_path": str(selected),
            "candidate_count": len(candidates),
        }

    def prepare_place_timing(self, inputs: dict[str, object]) -> dict[str, object]:
        """Initialize current-main iSTA for an ECC DreamPlace session."""
        if self._place_timing_active:
            self.destroy_place_timing()
        return self._start_place_timing(**_place_timing_kwargs(inputs))

    def refresh_place_timing(self, inputs: dict[str, object] | None = None) -> dict[str, object]:
        """Destroy and fully rebuild current-main iSTA after a native mutation."""
        if self._place_timing_active:
            self.destroy_place_timing()
        return self._start_place_timing(
            **_place_timing_kwargs(dict(inputs or self._place_timing_inputs or {}))
        )

    def destroy_place_timing(self) -> None:
        if not self._place_timing_active:
            return
        try:
            self.ecc.destroy_sta()
        finally:
            self._place_timing_active = False

    @property
    def place_timing_active(self) -> bool:
        return self._place_timing_active

    def build_macro_connection_map(self, max_hop: int):
        return self.ecc.build_macro_connection_map(max_hop)

    def build_connection_map(self, clusters, src_instances, max_hop: int):
        return self.ecc.build_connection_map(clusters, src_instances, max_hop)

    def reset_data(self):
        self.ecc.reset_data()

    ########################################################################
    # config api
    ########################################################################
    def init_config(self, db_config: PathArg, output_dir: PathArg, feature_dir: PathArg):
        """init_config"""
        self.ecc.db_init(
            config_path=db_config,
            output_path=output_dir,
            feature_path=feature_dir,
        )

    def update_step_paths(self, output_dir: PathArg, feature_dir: PathArg):
        self.ecc.db_init(
            output_path=output_dir,
            feature_path=feature_dir,
        )

    def update_sta_data_config(
        self, db_config: PathArg, output_dir: PathArg, lib_paths: list[PathArg], sdc_path: PathArg
    ):
        self.ecc.db_init(
            config_path=db_config,
            output_path=output_dir,
            lib_paths=path_list(lib_paths),
            sdc_path=sdc_path,
        )

    ########################################################################
    # data api
    ########################################################################
    def idb_init(self, config_path: PathArg):
        return self.ecc.idb_init(config_path)

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
    def init_techlef(self, tech_lef_path: PathArg):
        """init tech lef"""
        self.ecc.tech_lef_init(tech_lef_path)

    def init_lefs(self, lef_paths: list):
        """init_lef"""
        self.ecc.lef_init(lef_paths=lef_paths)

    def read_def(self, path: PathArg = "") -> bool:
        """init def"""
        return self.ecc.def_init(def_path=path)

    def read_verilog(self, verilog: PathArg, top_module: str) -> bool:
        """init verilog"""
        return self.ecc.verilog_init(verilog, top_module)

    def read_lvs_verilog(self, verilog: PathArg, top_module: str) -> bool:
        """init verilog for iLVS"""
        return self.ecc.lvs_verilog_init(verilog, top_module)

    def def_save(self, def_path: PathArg):
        """save def file"""
        self.ecc.def_save(def_name=def_path)

    def gds_save(self, output_path: PathArg, layer_map_path: PathArg) -> bool:
        """save gds file"""
        if not layer_map_path:
            raise ValueError(
                "PDK layer mapping file is required for GDS export; set pdk.mapping_file"
            )
        return self.ecc.gds_save(gds_name=output_path, layer_map_path=layer_map_path)

    def tcl_save(self, output_path: PathArg) -> bool:
        """Save hard-macro placement commands in Tcl format."""
        return self.ecc.tcl_save(output_path)

    def verilog_save(self, output_verilog, cell_names: set | None = None):
        """verilog save"""
        if cell_names is None:
            cell_names = set()
        self.ecc.netlist_save(netlist_path=output_verilog, exclude_cell_names=cell_names)

    def json_save(self, path: PathArg):
        self.ecc.json_save(path=path)

    def geometry_snapshot_save(
        self,
        output_dir: PathArg,
        *,
        include_drc: bool = False,
        thumbnail_path: PathArg | None = None,
    ):
        """Export the current in-memory IDB geometry for GUI rendering."""
        kwargs: dict[str, object] = {"output_dir": output_dir}
        if include_drc:
            kwargs["include_drc"] = True
        if thumbnail_path is not None:
            kwargs["thumbnail_path"] = thumbnail_path
        return self.ecc.geometry_snapshot_save(**kwargs)

    def initialize_geometry_session(self):
        """Begin a geometry edit session for incremental GUI updates."""
        return self.ecc.initialize_geometry_session()

    def sync_instance_geometry(self, inst_name: str):
        """Synchronize one edited instance from IDB into the geometry session."""
        return self.ecc.sync_instance_geometry(inst_name=inst_name)

    def geometry_session_snapshot_save(self, output_dir: PathArg):
        """Export the incremental geometry-session snapshot for GUI rendering."""
        return self.ecc.geometry_session_snapshot_save(output_dir=output_dir)

    def reset_geometry_session(self):
        """Discard the active geometry edit session."""
        return self.ecc.reset_geometry_session()

    def save_data(self, path: PathArg):
        """save ECC data"""
        return self.ecc.save_data(path=path)

    def load_data(self, path: PathArg):
        """load ECC data"""
        return self.ecc.load_data(path=path)

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

    def write_soc_json(self, path: PathArg, harden_cores: list[str] | None = None):
        """write SoC json"""
        if harden_cores is None:
            harden_cores = []
        return self.ecc.write_soc_json(path=path, harden_cores=harden_cores)

    ########################################################################
    # feature api
    ########################################################################
    def feature_sammry(self, json_path: PathArg):
        """
        generate feature summary
        """
        self.ecc.feature_summary(json_path)

    def feature_step(self, step: str, json_path: PathArg):
        """
        generate step feature
        """
        self.ecc.feature_tool(json_path, step)

    def feature_eval_map(self, path: PathArg, bin_cnt_x: int, bin_cnt_y: int):
        return self.ecc.feature_eval_map(
            path=path,
            bin_cnt_x=bin_cnt_x,
            bin_cnt_y=bin_cnt_y,
        )

    def feature_eval_summary(self, path: PathArg, grid_size: int):
        return self.ecc.feature_eval_summary(path=path, grid_size=grid_size)

    def feature_timing_eval_summary(self, path: PathArg):
        return self.ecc.feature_timing_eval_summary(path=path)

    def feature_net_eval(self, path: PathArg):
        return self.ecc.feature_net_eval(path=path)

    def feature_cong_map(self, step: str, dir: PathArg):
        return self.ecc.feature_cong_map(step=step, dir=dir)

    ########################################################################
    # reports api
    ########################################################################
    def report_wirelength(self, path: PathArg = ""):
        return self.ecc.report_wirelength(path=path)

    def report_summary(self, path: PathArg):
        """
        generate step report
        """
        self.ecc.report_db(path)

    def report_congestion(self, path: PathArg = ""):
        return self.ecc.report_congestion(path=path)

    def report_dangling_net(self, path: PathArg = ""):
        return self.ecc.report_dangling_net(path=path)

    def report_route(
        self,
        path: PathArg = "",
        net: str = "",
        *,
        summary: bool = True,
    ):
        return self.ecc.report_route(path=path, net=net, summary=summary)

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

    def report_drc(self, path: PathArg):
        return self.ecc.report_drc(path=path)

    ########################################################################
    # CTS api
    ########################################################################
    def run_cts(self, config: PathArg, output: PathArg) -> bool:
        return self.ecc.run_cts(config, output)

    def report_cts(self, output: PathArg):
        self.ecc.cts_report(output)

    def feature_cts_timing(self) -> dict:
        """Return post-optimization CTS FastSTA timing aggregates."""
        return self.ecc.cts_timing_feature()

    def feature_cts_map(self, json_path: PathArg, map_grid_size=5):
        """
        generate cts map feature
        """
        self.ecc.feature_cts_eval(json_path, map_grid_size)

    ########################################################################
    # DRC api
    ########################################################################
    def init_drc(self, output_dir: PathArg, therad_number: int = 128):
        """
        init drc config
        """
        self.ecc.init_drc(temp_directory_path=output_dir, thread_number=therad_number)

    def run_drc(self) -> bool:
        """
        run drc check
        """
        return self.ecc.run_drc()

    def destroy_drc(self) -> bool:
        """
        release drc resources
        """
        return self.ecc.destroy_drc()

    ########################################################################
    # LVS api
    ########################################################################
    def init_lvs(self, output_dir: PathArg, thread_number: int = 128):
        return self.ecc.init_lvs(
            temp_directory_path=output_dir,
            thread_number=thread_number,
        )

    def run_lvs(self):
        return self.ecc.run_lvs()

    def destroy_lvs(self):
        return self.ecc.destroy_lvs()

    ########################################################################
    # floorplan api
    ########################################################################
    def init_fp(self, config: PathArg):
        return self.ecc.init_fp(config=config)

    def run_simple_fp(self):
        return self.ecc.run_simple_fp()

    def run_fp(self):
        return self.ecc.run_fp()

    def destroy_fp(self):
        return self.ecc.destroy_fp()

    ########################################################################
    # placement api
    ########################################################################
    def feature_placement_map(self, json_path: PathArg, map_grid_size=5):
        """
        generate placement map feature
        """
        self.ecc.feature_pl_eval(json_path, map_grid_size)

    ########################################################################
    # iMJ api
    ########################################################################
    def init_mj(self, output_dir: PathArg) -> bool:
        return self.ecc.init_mj(config_dict={"-temp_directory_path": os.fspath(output_dir)})

    def run_filler(self, config: PathArg) -> bool:
        return self.ecc.insert_filler(config=config)

    def check_antenna(self, step_json: PathArg | None = None) -> bool:
        config_dict = {}
        if step_json:
            config_dict["-step_json"] = path_text(step_json)
        return self.ecc.check_antenna(config_dict=config_dict)

    def destroy_mj(self) -> bool:
        return self.ecc.destroy_mj()

    ########################################################################
    # routing api
    ########################################################################
    def run_ert(self, config: PathArg = "", config_dict: dict[str, str] | None = None):
        if config_dict is None:
            config_dict = {}
        return self.ecc.run_ert(config=config, config_dict=config_dict)

    def run_routing(self, config: PathArg):
        self.ecc.init_rt(config=config)
        self.ecc.run_rt()
        self.ecc.destroy_rt()

    def close_routing(self):
        self.ecc.destroy_rt()

    # read route json file to ecc route data
    def feature_route_read(self, json_path: PathArg):
        self.ecc.feature_route_read(path=json_path)

    # read route def and save route data to json
    def feature_route(self, json_path: PathArg):
        self.ecc.feature_route(path=json_path)

    ########################################################################
    # RCX api
    ########################################################################
    def init_rcx(self, config: PathArg, pdk: str = "ics55"):
        if pdk:
            return self.ecc.init_rcx(config=config, pdk=pdk)
        return self.ecc.init_rcx(config=config)

    def run_rcx(self):
        return self.ecc.run_rcx()

    def destroy_rcx(self):
        destroy_rcx = getattr(self.ecc, "destroy_rcx", None)
        if destroy_rcx is None:
            return None
        return destroy_rcx()

    ########################################################################
    # power analysis api
    ########################################################################
    def init_pw(
        self,
        output_dir: PathArg,
        lib_paths: list[Path] | list[str] | None = None,
        sdc_path: PathArg = "",
        spef_path: PathArg = "",
    ):
        if lib_paths is None:
            lib_paths = []
        if not self.ecc.lib_init(lib_paths=lib_paths):
            return False
        self.ecc.sdc_init(sdc_path)
        self.ecc.spef_init(spef_path)
        return self.ecc.init_pw(config_dict={"-temp_directory_path": os.fspath(output_dir)})

    def run_pw(self):
        return self.ecc.run_pw()

    def destroy_pw(self):
        return self.ecc.destroy_pw()

    ########################################################################
    # EMIR api
    ########################################################################
    def init_emir(
        self,
        output_dir: PathArg,
        instance_power_file_path: PathArg,
        technology_file_path: PathArg,
        ploc_file_path: PathArg,
    ):
        return self.ecc.init_emir(
            temp_directory_path=output_dir,
            instance_power_file_path=instance_power_file_path,
            technology_file_path=technology_file_path,
            ploc_file_path=ploc_file_path,
        )

    def run_emir(self):
        return self.ecc.run_emir()

    def destroy_emir(self):
        return self.ecc.destroy_emir()

    ########################################################################
    # STA api
    ########################################################################
    def run_timing(
        self,
        config: PathArg = "",
        work_dir: PathArg = "",
        report_dir: PathArg = "",
        feature_dir: PathArg = "",
        lib_paths: list[Path] | list[str] | None = None,
        sdc_path: PathArg = "",
        spef_path: PathArg = "",
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

        if not self.ecc.lib_init(lib_paths=lib_paths):
            raise RuntimeError("Failed to load Liberty libraries for STA")
        self.ecc.sdc_init(sdc_path)
        self.ecc.spef_init(spef_path)
        config_dict = {}
        if work_dir:
            config_dict["-temp_directory_path"] = os.fspath(work_dir)
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
        self.ecc.init_sta(config=config, config_dict=config_dict)
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
        return self.ecc.write_abstract_lef(output_lef_path)

    def write_timing_model(
        self,
        output_lib_path: PathArg,
        analysis_mode: str = "max",
        config: PathArg = "",
        output_dir: PathArg = "",
        lib_paths: list[str] | None = None,
        sdc_path: PathArg = "",
        spef_path: PathArg = "",
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
        if not self.ecc.lib_init(lib_paths=lib_paths):
            raise RuntimeError("Failed to load Liberty libraries for timing model")
        self.ecc.sdc_init(sdc_path)
        self.ecc.spef_init(spef_path)
        config_dict = {"-temp_directory_path": os.fspath(sta_output_dir)}
        self.ecc.init_sta(config=config, config_dict=config_dict)
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
