#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import importlib.machinery
import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
    
class DreamplaceModule:
    def __init__(
        self,
        workspace: Workspace,
        step: WorkspaceStep,
        ecc_module: ECCToolsModule,
        input_def: str,
        input_verilog: str,
        output_def: str,
        output_verilog: str,
    ):
        self.workspace = workspace
        self.step = step
        self.ecc_module = ecc_module
        self.input_def = input_def
        self.input_verilog = input_verilog
        self.output_def = output_def
        self.output_verilog = output_verilog
        self.param_path = step.config["dreamplace"]
        self.result_dir = step.data.get(step.name, step.data["dir"])

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

    @contextmanager
    def _configure_root_logging(self, legalize_only: bool):
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        log_file = self.step.log.get("file") or self._log_path(legalize_only)
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("[%(levelname)-7s] %(message)s"))
        root_logger.addHandler(file_handler)
        if original_level > logging.INFO:
            root_logger.setLevel(logging.INFO)

        try:
            yield
        finally:
            root_logger.removeHandler(file_handler)
            file_handler.close()
            root_logger.setLevel(original_level)
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    def _run(self, legalize_only: bool) -> bool:
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine

        with self._configure_root_logging(legalize_only):
            params = self._build_params(Params, legalize_only=legalize_only)

            engine = PlacementEngine(params)
            engine.setup_rawdb(ecc_module=self.ecc_module)
            ppa = engine.run()

            if ppa.get("hpwl") == float("inf"):
                LOGGER = logging.getLogger(__name__)
                LOGGER.error("dreamplace failed for %s", self.step.name)
                return False

            return True

    def run_placement(self) -> bool:
        return self._run(legalize_only=False)

    def run_legalization(self) -> bool:
        if self.step.name != StepEnum.LEGALIZATION.value:
            return False
        return self._run(legalize_only=True)

__all__ = ["DreamplaceModule"]
