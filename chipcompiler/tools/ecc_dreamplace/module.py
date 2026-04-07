#!/usr/bin/env python

import json
import logging
import os

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc_dreamplace.utility import ensure_dreamplace_import_path


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

    def _run(self, legalize_only: bool) -> bool:
        ensure_dreamplace_import_path()
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine

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
