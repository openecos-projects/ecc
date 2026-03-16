#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep

from .module import ECCToolsModule


LOGGER = logging.getLogger(__name__)


def _thirdparty_root() -> Path:
    return Path(__file__).resolve().parents[2] / "thirdparty" / "ecc-dreamplace"


def _ensure_import_path() -> None:
    root = str(_thirdparty_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_dreamplace():
    _ensure_import_path()

    from dreamplace.Params import Params
    from dreamplace.Placer import PlacementEngine

    return Params, PlacementEngine


def is_dreamplace_available() -> bool:
    try:
        _load_dreamplace()
    except Exception as exc:
        LOGGER.debug("dreamplace import failed: %s", exc, exc_info=True)
        return False
    return True


class _LogContext:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.logger = logging.getLogger()
        self.original_handlers = []
        self.original_level = logging.INFO
        self.file_handler = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.original_handlers = list(self.logger.handlers)
        self.original_level = self.logger.level
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        self.file_handler = logging.FileHandler(self.log_path, mode="w")
        self.file_handler.setFormatter(
            logging.Formatter("[%(levelname)-7s] %(name)s - %(message)s")
        )
        self.logger.addHandler(self.file_handler)
        self.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.file_handler is not None:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()
        for handler in self.original_handlers:
            self.logger.addHandler(handler)
        self.logger.setLevel(self.original_level)
        return False


class EccStaAdapter:
    def __init__(self, module: ECCToolsModule):
        self.module = module

    def init_sta(self):
        return None

    def build_rc_tree_from_flat_data(self, *args, **kwargs):
        raise NotImplementedError("ecc dreamplace STA bridge is not implemented in this runtime")

    def update_and_get_all_pin_timings(self, *args, **kwargs):
        raise NotImplementedError("ecc dreamplace STA bridge is not implemented in this runtime")


class EccDbAdapter:
    def __init__(
        self,
        dir_workspace: str,
        module: ECCToolsModule,
        input_def: str = "",
        input_verilog: str = "",
        output_def: str = "",
        output_verilog: str = "",
    ):
        self.dir_workspace = dir_workspace
        self.module = module
        self.input_def = input_def
        self.input_verilog = input_verilog
        self.output_def = output_def
        self.output_verilog = output_verilog
        self._sta_adapter = None

    def read_def(self, path: str = ""):
        self.module.read_def(path or self.input_def)

    def def_save(self, def_path: str):
        self.module.def_save(def_path)

    def tcl_save(self, output_path: str):
        self.module.tcl_save(output_path)

    def get_dmInst_ptr(self):
        return self.module.get_dmInst_ptr()

    def pydb(
        self,
        dm_inst_ptr,
        route_num_bins_x: int,
        route_num_bins_y: int,
        routability_opt_flag: int,
        with_sta: int,
    ):
        return self.module.pydb(
            dm_inst_ptr,
            route_num_bins_x,
            route_num_bins_y,
            routability_opt_flag,
            with_sta,
        )

    def write_placement_back(self, dm_inst_ptr, node_x, node_y):
        self.module.write_placement_back(dm_inst_ptr, node_x, node_y)

    def build_macro_connection_map(self, max_hop: int):
        return self.module.build_macro_connection_map(max_hop)

    def get_sta_adapter(self):
        if self._sta_adapter is None:
            self._sta_adapter = EccStaAdapter(self.module)
        return self._sta_adapter


class DreamPlace:
    def __init__(
        self,
        workspace: Workspace,
        step: WorkspaceStep,
        module: ECCToolsModule,
        input_def: str,
        input_verilog: str,
        output_def: str,
        output_verilog: str,
    ):
        self.workspace = workspace
        self.step = step
        self.module = module
        self.input_def = input_def
        self.input_verilog = input_verilog
        self.output_def = output_def
        self.output_verilog = output_verilog
        self.param_path = step.config["dreamplace"]
        self.result_dir = str(Path(step.data.get(step.name, step.data["dir"])) / "dreamplace")

    def _build_params(self, params_cls, legalize_only: bool):
        with open(self.param_path, encoding="utf-8") as f_reader:
            config = json.load(f_reader)

        params = params_cls()
        params.fromJson(config)
        params.def_input = self.input_def
        params.verilog_input = self.input_verilog
        params.result_dir = self.result_dir
        params.base_design_name = self.workspace.design.name
        params.with_sta = False
        params.timing_opt_flag = 0
        params.timing_eval_flag = 0
        params.differentiable_timing_obj = 0

        if legalize_only:
            params.global_place_flag = 0
            params.legalize_flag = 1
            params.enable_fillers = 0
            params.random_center_init_flag = 0
            params.auto_adjust_bins = 1

        return params

    def _log_path(self, legalize_only: bool) -> str:
        log_name = "dreamplace_legalization.log" if legalize_only else "dreamplace_placement.log"
        return os.path.join(self.result_dir, log_name)

    def _run(self, legalize_only: bool) -> bool:
        Params, PlacementEngine = _load_dreamplace()
        params = self._build_params(Params, legalize_only=legalize_only)
        data_manager = EccDbAdapter(
            dir_workspace=self.step.directory,
            module=self.module,
            input_def=self.input_def,
            input_verilog=self.input_verilog,
            output_def=self.output_def,
            output_verilog=self.output_verilog,
        )

        with _LogContext(self._log_path(legalize_only)):
            engine = PlacementEngine(params)
            engine.setup_rawdb(data_manager=data_manager)
            ppa = engine.run()

        if ppa.get("hpwl") == float("inf"):
            LOGGER.error("dreamplace failed for %s", self.step.name)
            return False

        return True

    def run_placement(self) -> bool:
        return self._run(legalize_only=False)

    def run_legalization(self) -> bool:
        if self.step.name != StepEnum.LEGALIZATION.value:
            return False
        return self._run(legalize_only=True)
