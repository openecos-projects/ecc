#!/usr/bin/env python

import json
import logging
import math
import os
import sys
from contextlib import contextmanager, suppress
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import SkippableStepEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.utility.path import optional_path, path_text

_LEGALIZE_OWNERS = frozenset(
    {
        StepEnum.LEGALIZATION.value,
        SkippableStepEnum.TIMING_OPT.value,
    }
)


class DreamplaceRunMode(Enum):
    PLACEMENT = "placement"
    DIFF_SIZING = "diff_sizing"
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
        param_path = self.param_path
        if mode is DreamplaceRunMode.DIFF_SIZING:
            from .builder import step_config_path

            generated_path = step_config_path(self.workspace, self.step)
            if generated_path.is_file():
                param_path = generated_path
        with open(param_path, encoding="utf-8") as f_reader:
            config = json.load(f_reader)
        if config.get("cell_model_schema") is None:
            config.pop("cell_model_schema", None)

        if mode is DreamplaceRunMode.DIFF_SIZING:
            from .builder import _apply_diff_sizing_defaults

            config = _apply_diff_sizing_defaults(config)
        elif mode is not DreamplaceRunMode.PLACEMENT:
            config.update(
                place_io_engine="ecc",
                flow_kind="placement",
                placement_sizing_mode="place_only",
                sizing_parameterization="logits",
                diff_timing_driven_placement=0,
                differentiable_timing_obj=0,
                with_sta=0,
                timing_rc_mode="placement",
                timing_opt_flag=0,
                timing_eval_flag=0,
                enable_net_weighting=0,
                pin2pin_net_weighting=0,
                timing_opt_enabled=0,
                inflation_s5b1_enabled=0,
                routability_opt_flag=0,
                l_shape_routability_flag=0,
                adjust_gpugr_area_flag=0,
                gpugr_final_eval_flag=0,
                buffering_continuous_relaxed_optimization=False,
                buffering_segment_count_tns_gradient=False,
                buffering_segment_strategy="continuous",
                buffering_candidate_strategy="continuous",
                joint_segment_virtual_density_enabled=0,
            )

        params = params_cls()
        params.fromJson(config)
        for name in config:
            setattr(params, f"_{name}_explicit", True)

        from dreamplace.flows.flow_config import apply_flow_defaults

        apply_flow_defaults(params)
        # DREAMPlace's Params.def_input/verilog_input feed a std::string C++
        # option (place_io) and are json.dump-ed by Params.dump, so normalize to
        # str at this native boundary (path_text: None -> "").
        params.def_input = path_text(self.input_def)
        params.verilog_input = path_text(self.input_verilog)
        params.result_dir = self.result_dir
        params.base_design_name = self.workspace.design.name

        params.macro_only = 0
        if mode is DreamplaceRunMode.MACRO_PLACEMENT:
            params.macro_only = 1
            params.detailed_place_flag = 0
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
            params.detailed_place_flag = int(self.step.name != StepEnum.LEGALIZATION.value)
            params.enable_fillers = 0
            params.random_center_init_flag = 0
            params.auto_adjust_bins = 1
            params.cell_padding_x = 0
            params.post_legalization_adaptive_padding_flag = 0

        if mode is DreamplaceRunMode.DIFF_SIZING:
            params.place_io_engine = "ecc"
            params.design_inputs = self._ecc_design_inputs(params)
        elif mode is not DreamplaceRunMode.PLACEMENT:
            params.place_io_engine = "ecc"
            params.diff_timing_driven_placement = 0
            params.with_sta = 0
            params.timing_opt_flag = 0
            params.timing_eval_flag = 0
            params.differentiable_timing_obj = 0
        elif getattr(params, "place_io_engine", "ieda") == "openroad":
            params.design_inputs = self._openroad_design_inputs(params)
        elif getattr(params, "place_io_engine", "ieda") == "ecc":
            if self._timing_active(params):
                params.design_inputs = self._ecc_design_inputs(params)

        return params

    def _resolve_pdk_path(self, value) -> str:
        if not value:
            return ""
        path = Path(value)
        if path.is_absolute():
            return str(path)
        pdk_root = getattr(self.workspace.pdk, "root", None)
        return str((Path(pdk_root) / path) if pdk_root else path)

    @staticmethod
    def _timing_active(params) -> bool:
        return bool(
            getattr(params, "diff_timing_driven_placement", 0)
            or getattr(params, "differentiable_timing_obj", 0)
            or getattr(params, "with_sta", 0)
            or getattr(params, "timing_eval_flag", 0)
            or getattr(params, "flow_kind", "placement") in {"sta", "sizing", "buffering", "joint"}
        )

    def _openroad_design_inputs(self, params) -> dict:
        existing = dict(getattr(params, "design_inputs", {}) or {})
        rc_tcl = self._resolve_pdk_path(getattr(params, "rc_tcl", "") or existing.get("rc_tcl"))
        if self._timing_active(params) and not rc_tcl:
            raise ValueError("timing-active OpenROAD placement requires place.rc_tcl")
        if rc_tcl and not Path(rc_tcl).is_file():
            raise FileNotFoundError(f"OpenROAD RC Tcl does not exist: {rc_tcl}")

        return {
            **existing,
            "tech_lef": path_text(getattr(self.workspace.pdk, "tech", None)),
            "lef": [str(path) for path in getattr(self.workspace.pdk, "lefs", [])],
            "lib": [str(path) for path in getattr(self.workspace.pdk, "libs", [])],
            "def": path_text(self.input_def),
            "verilog": path_text(self.input_verilog),
            "sdc": path_text(getattr(self.workspace.pdk, "sdc", None)),
            "rc_tcl": rc_tcl,
        }

    def _ecc_design_inputs(self, params) -> dict:
        existing = dict(getattr(params, "design_inputs", {}) or {})
        gr_timing = getattr(params, "timing_rc_mode", "placement") == "gr"
        sta_config = existing.get("sta_config")
        if not sta_config:
            sta_config = self.workspace.config.get("sta", "")
        rcx_config = existing.get("rcx_config", "")
        if gr_timing:
            # Native STA supplies cell/SDC metadata. GRParasiticsOp owns wire
            # RC, so neither initial nor terminal export needs native RCX/SPEF.
            rcx_config = ""
            existing.pop("spef_path", None)
        return {
            **existing,
            "tech_lef": path_text(getattr(self.workspace.pdk, "tech", None)),
            "lef": [str(path) for path in getattr(self.workspace.pdk, "lefs", [])],
            "lib": [str(path) for path in getattr(self.workspace.pdk, "libs", [])],
            "def": path_text(self.input_def),
            "verilog": path_text(self.input_verilog),
            "sdc": path_text(getattr(self.workspace.pdk, "sdc", None)),
            "spef": "" if gr_timing else path_text(getattr(self.workspace.pdk, "spef", None)),
            "sta_config": path_text(sta_config),
            "rcx_config": path_text(rcx_config),
            "rcx_pdk": str(getattr(self.workspace.pdk, "name", "") or ""),
            "work_dir": str(Path(self.result_dir) / "native_sta"),
            "thread_number": int(getattr(params, "num_threads", 2) or 2),
            "max_paths": 20,
        }

    def _log_path(self, *, mode: DreamplaceRunMode) -> str:
        log_name = {
            DreamplaceRunMode.PLACEMENT: "dreamplace_placement.log",
            DreamplaceRunMode.DIFF_SIZING: "dreamplace_diff_sizing.log",
            DreamplaceRunMode.MACRO_PLACEMENT: "dreamplace_macro_placement.log",
            DreamplaceRunMode.LEGALIZATION: "dreamplace_legalization.log",
        }[mode]
        return os.path.join(self.result_dir, log_name)

    def _file_handler_path(self, *, mode: DreamplaceRunMode) -> str:
        if mode is DreamplaceRunMode.MACRO_PLACEMENT:
            return self._log_path(mode=mode)
        if mode is DreamplaceRunMode.LEGALIZATION and self.step.name != StepEnum.LEGALIZATION.value:
            return self._log_path(mode=mode)
        return str(self.step.log.file or self._log_path(mode=mode))

    @contextmanager
    def _configure_root_logging(self, *, mode: DreamplaceRunMode):
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        log_file = self._file_handler_path(mode=mode)
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
            place_io_engine = getattr(params, "place_io_engine", "ieda")
            if place_io_engine == "openroad":
                data_manager = SimpleNamespace(dir_workspace=str(self.workspace.directory))
            else:
                if self.ecc_module is None:
                    raise RuntimeError("iEDA placement requires an initialized ECC database")
                data_manager = self.ecc_module
                with suppress(AttributeError):
                    data_manager.dir_workspace = str(self.workspace.directory)
            engine.setup_rawdb(data_manager=data_manager)
            ppa = engine.run()

            skipped_empty_macro_placement = (
                mode is DreamplaceRunMode.MACRO_PLACEMENT
                and ppa.get("executed") is False
                and ppa.get("candidate_count") == 0
                and ppa.get("reason") == "no_unplaced_hard_macros"
            )
            if skipped_empty_macro_placement:
                return True

            status = str(ppa.get("status") or "").lower()
            if status and status not in {"ok", "success", "completed"}:
                logging.getLogger(__name__).error("dreamplace failed for %s", self.step.name)
                return False

            hpwl = ppa.get("hpwl")
            if not status and (hpwl is None or not math.isfinite(float(hpwl))):
                logging.getLogger(__name__).error("dreamplace failed for %s", self.step.name)
                return False

            if place_io_engine in {"openroad", "ecc"}:
                if self.output_def:
                    engine.write_back(str(self.output_def))
                if place_io_engine in {"openroad", "ecc"} and self.output_verilog:
                    engine.write_verilog(str(self.output_verilog))

            return True

    def run_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.PLACEMENT)

    def run_diff_sizing(self) -> bool:
        return self._run(mode=DreamplaceRunMode.DIFF_SIZING)

    def run_macro_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.MACRO_PLACEMENT)

    def run_legalization(self) -> bool:
        if self.step.name not in _LEGALIZE_OWNERS:
            return False
        return self._run(mode=DreamplaceRunMode.LEGALIZATION)


__all__ = ["DreamplaceModule", "DreamplaceRunMode"]
