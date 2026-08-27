#!/usr/bin/env python

import json
import logging
import os
import sys
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.utility.path import optional_path, path_text


class DreamplaceRunMode(Enum):
    PLACEMENT = "placement"
    MACRO_PLACEMENT = "macro_placement"
    LEGALIZATION = "legalization"


class DreamplaceModule:
    def __init__(
        self,
        workspace: Workspace,
        step: WorkspaceStep,
        ecc_module: ECCToolsModule,
        input_def: Path | None,
        input_verilog: Path | None,
        output_def: Path | None,
        output_verilog: Path | None,
    ):
        self.workspace = workspace
        self.step = step
        self.ecc_module = ecc_module
        self.input_def = optional_path(input_def)
        self.input_verilog = optional_path(input_verilog)
        self.output_def = optional_path(output_def)
        self.output_verilog = optional_path(output_verilog)
        self.param_path = workspace.config["dreamplace"]
        self.result_dir = str(step.data.workdir_for(step.name))

    def _build_params(self, params_cls, *, mode: DreamplaceRunMode):
        with open(self.param_path, encoding="utf-8") as f_reader:
            config = json.load(f_reader)

        params = params_cls()
        params.fromJson(config)
        # DREAMPlace's Params.def_input/verilog_input feed a std::string C++
        # option (place_io) and are json.dump-ed by Params.dump, so normalize to
        # str at this native boundary (path_text: None -> "").
        params.def_input = path_text(self.input_def)
        params.verilog_input = path_text(self.input_verilog)
        params.result_dir = self.result_dir
        params.base_design_name = self.workspace.design.name
        params.with_sta = False
        params.timing_opt_flag = 0
        params.timing_eval_flag = 0
        params.differentiable_timing_obj = 0

        params.macro_only = 0
        if mode is DreamplaceRunMode.MACRO_PLACEMENT:
            params.macro_only = 1
            params.global_place_flag = 1
            params.macro_place_flag = 1
            params.legalize_flag = 1
            params.two_stage_flag = 0
            params.macro_halo_x = 2000
            params.macro_halo_y = 2000
            params.routability_opt_flag = 0
            params.get_congestion_map = 0
            params.egr_padding_flag = 0
        elif mode is DreamplaceRunMode.LEGALIZATION:
            params.global_place_flag = 0
            params.legalize_flag = 1
            params.enable_fillers = 0
            params.random_center_init_flag = 0
            params.auto_adjust_bins = 1

        return params

    def _log_path(self, *, mode: DreamplaceRunMode) -> str:
        log_name = {
            DreamplaceRunMode.PLACEMENT: "dreamplace_placement.log",
            DreamplaceRunMode.MACRO_PLACEMENT: "dreamplace_macro_placement.log",
            DreamplaceRunMode.LEGALIZATION: "dreamplace_legalization.log",
        }[mode]
        return os.path.join(self.result_dir, log_name)

    @contextmanager
    def _configure_root_logging(self, *, mode: DreamplaceRunMode):
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        log_file = self.step.log.file or self._log_path(mode=mode)
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

        formatter = logging.Formatter("[%(levelname)-7s] %(message)s")
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setFormatter(formatter)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stdout_handler)
        if original_level > logging.INFO:
            root_logger.setLevel(logging.INFO)

        try:
            yield
        finally:
            root_logger.removeHandler(file_handler)
            root_logger.removeHandler(stdout_handler)
            file_handler.close()
            stdout_handler.close()
            root_logger.setLevel(original_level)
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    def _run(self, *, mode: DreamplaceRunMode) -> bool:
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine

        with self._configure_root_logging(mode=mode):
            params = self._build_params(Params, mode=mode)

            engine = PlacementEngine(params)
            engine.setup_rawdb(ecc_module=self.ecc_module)
            ppa = engine.run()

            skipped_empty_macro_placement = (
                mode is DreamplaceRunMode.MACRO_PLACEMENT
                and ppa.get("executed") is False
                and ppa.get("candidate_count") == 0
                and ppa.get("reason") == "no_unplaced_hard_macros"
            )
            if skipped_empty_macro_placement:
                return True

            if ppa.get("hpwl", float("inf")) == float("inf"):
                logging.getLogger(__name__).error("dreamplace failed for %s", self.step.name)
                return False

            return True

    def run_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.PLACEMENT)

    def run_macro_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.MACRO_PLACEMENT)

    def run_legalization(self) -> bool:
        if self.step.name != StepEnum.LEGALIZATION.value:
            return False
        return self._run(mode=DreamplaceRunMode.LEGALIZATION)


__all__ = ["DreamplaceModule", "DreamplaceRunMode"]
