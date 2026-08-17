#!/usr/bin/env python
import os
import shutil
from pathlib import Path
from typing import TypeAlias

from numpy import double

from chipcompiler.tools.ecc.sta_artifacts import discard_sta_run_outputs, publish_sta_artifacts
from chipcompiler.utility.path import path_text, path_texts

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
        except ImportError:
            try:
                from chipcompiler.tools.ecc.bin import ecc_py as ecc
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

    def close(self):
        """release ECC data without terminating the host process"""
        self.reset_data()

    def export_place_db(
        self,
        route_num_bins_x: int,
        route_num_bins_y: int,
        *,
        routability: bool = False,
        with_sta: bool = False,
    ):
        return self.ecc.pydb(
            route_num_bins_x,
            route_num_bins_y,
            routability,
            with_sta,
        )

    def reset_data(self):
        self.ecc.reset_data()

    ########################################################################
    # config api
    ########################################################################

    def init_config(
        self, db_config: str, output_dir: PathArg, feature_dir: PathArg
    ):
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

    def set_net(self, net_name: str, net_type: str):
        """
        set net type
        """
        return self.ecc.set_net(net_name=net_name, net_type=net_type)

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

    def apply_placement(self, node_x, node_y):
        self.ecc.write_placement_back(node_x, node_y)

    ########################################################################
    # data io api
    ########################################################################

    def init_techlef(self, tech_lef_path: str):
        """init tech lef"""
        self.ecc.tech_lef_init(path_text(tech_lef_path))

    def init_lefs(self, lef_paths: list):
        """init_lef"""
        self.ecc.lef_init(lef_paths=path_texts(lef_paths))

    def read_def(self, path: str = ""):
        """init def"""
        self.ecc.def_init(def_path=path_text(path))

    def read_verilog(self, verilog: PathArg, top_module: str):
        """init verilog"""
        self.ecc.verilog_init(path_text(verilog), top_module)

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

    def report_summary(self, path: PathArg):
        """
        generate step report
        """
        self.ecc.report_db(path_text(path))

    def run_cts(self, config: str, output: PathArg) -> bool:
        return self.ecc.run_cts(path_text(config), path_text(output))

    def report_cts(self, output: PathArg):
        self.ecc.cts_report(path_text(output))

    def feature_cts_timing(self) -> dict:
        """Return post-optimization CTS FastSTA timing aggregates."""
        return self.ecc.cts_timing_feature()

    def feature_cts_map(self, json_path: PathArg, map_grid_size=1):
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

    def feature_placement_map(self, json_path: PathArg, map_grid_size=1):
        """
        generate placement map feature
        """
        self.ecc.feature_pl_eval(path_text(json_path), map_grid_size)

    def run_filler(self, config: str):
        self.ecc.insert_filler(path_text(config))

    def run_routing(self, config: str):
        self.ecc.init_rt(config=path_text(config))
        self.ecc.run_rt()
        self.ecc.destroy_rt()

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

    def run_net_opt(self, config: str):
        return self.ecc.fix_fanout(path_text(config))


