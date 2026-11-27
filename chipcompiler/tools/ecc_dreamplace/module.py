#!/usr/bin/env python

import json
import logging
import math
import os
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import SkippableStepEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.timing_constraints import prepare_timing_context, step_tcl_path
from chipcompiler.utility.path import optional_path

from .run_modes import GEOMETRY_ONLY_CONFIG, MODE_FLAGS, DreamplaceRunMode

_LEGALIZE_OWNERS = frozenset(
    {
        StepEnum.LEGALIZATION.value,
        SkippableStepEnum.TIMING_OPT.value,
    }
)


class DreamplaceModule:
    def __init__(
        self,
        workspace: Workspace,
        step: WorkspaceStep,
        ecc_module: ECCToolsModule | None,
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
        from .builder import step_config_path

        self.param_path = step_config_path(workspace, step)
        self.result_dir = str(step.data.workdir_for(step.name))

    def _build_params(self, params_cls, *, mode: DreamplaceRunMode):
        if not self.param_path.is_file():
            raise FileNotFoundError(f"DreamPlace step config is missing: {self.param_path}")
        with open(self.param_path, encoding="utf-8") as f_reader:
            config = json.load(f_reader)
        if config.get("cell_model_schema") is None:
            config.pop("cell_model_schema", None)

        if mode is DreamplaceRunMode.DIFF_OPT:
            from .diff_opt import apply_diff_opt_defaults

            config = apply_diff_opt_defaults(config)
        elif mode is DreamplaceRunMode.DIFF_SIZING:
            from .builder import _apply_diff_sizing_defaults

            config = _apply_diff_sizing_defaults(config)
        elif mode is not DreamplaceRunMode.PLACEMENT:
            config.update(GEOMETRY_ONLY_CONFIG)

        params = params_cls()
        params.fromJson(config)
        for name in config:
            setattr(params, f"_{name}_explicit", True)

        from dreamplace.flows.config.resolver import apply_flow_defaults

        apply_flow_defaults(params)
        # Params normalizes path-like values to str on assignment (they are also
        # json.dump-ed by Params.dump), so hand over Path | None as-is; None
        # keeps the "unset" spelling the C++ options expect.
        params.def_input = self.input_def or ""
        params.verilog_input = self.input_verilog or ""
        params.result_dir = self.result_dir
        params.base_design_name = self.workspace.design.name

        params.macro_only = 0
        # Already in the step file (``force_mode_config``); the flow defaults
        # above must not override the stages this mode runs.
        for name, value in MODE_FLAGS.get(mode, {}).items():
            setattr(params, name, value)

        if mode in (
            DreamplaceRunMode.DIFF_OPT,
            DreamplaceRunMode.DIFF_SIZING,
        ):
            params.place_io_engine = "ecc"
            params.design_inputs = self._ecc_design_inputs(params)
            if mode is DreamplaceRunMode.DIFF_OPT:
                params.design_inputs.update(spef="", spef_path="", rcx_config="")
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

    def _resolve_pdk_path(self, value) -> Path | str:
        if not value:
            return ""
        path = Path(value)
        if path.is_absolute():
            return path
        pdk_root = getattr(self.workspace.pdk, "root", None)
        return (Path(pdk_root) / path) if pdk_root else path

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

        prepare_timing_context(self.workspace, self.step, self.ecc_module)

        return {
            **existing,
            "tech_lef": getattr(self.workspace.pdk, "tech", None) or "",
            "lef": list(getattr(self.workspace.pdk, "lefs", None) or []),
            "lib": list(getattr(self.workspace.pdk, "libs", None) or []),
            "def": self.input_def or "",
            "verilog": self.input_verilog or "",
            "sdc": step_tcl_path(self.workspace, self.step) or "",
            "rc_tcl": rc_tcl,
        }

    def _ecc_design_inputs(self, params) -> dict:
        existing = dict(getattr(params, "design_inputs", {}) or {})
        rc_mode = getattr(params, "timing_rc_mode", "placement")
        spef_rc = rc_mode == "spef"
        frozen_rc = rc_mode in {"gr", "spef"}
        if spef_rc:
            spef_input = str(getattr(params, "spef_input", "") or "").strip()
            if not spef_input:
                fallback = (
                    existing.get("spef_input")
                    or existing.get("spef")
                    or getattr(self.workspace.pdk, "spef", None)
                    or ""
                )
                spef_input = str(fallback).strip()
            if spef_input:
                candidate = Path(spef_input)
                if not candidate.is_absolute() and getattr(self.workspace, "directory", None):
                    ws_candidate = Path(self.workspace.directory) / candidate
                    if ws_candidate.is_file():
                        candidate = ws_candidate
                    else:
                        candidate = Path(self._resolve_pdk_path(spef_input))
                params.spef_input = str(candidate)
        sta_config = existing.get("sta_config")
        if not sta_config:
            sta_config = self.workspace.config.get("sta", "")
        rcx_config = existing.get("rcx_config", "")
        if frozen_rc:
            # GRParasiticsOp and SPEF snapshots supply wire RC without running
            # native RCX extraction. SPEF mode still feeds its post-route SPEF
            # and complete propagated-clock STA to native STA.
            rcx_config = ""
            existing.pop("spef_path", None)
        spef = (
            str(getattr(params, "spef_input", "") or "")
            if spef_rc
            else ("" if rc_mode == "gr" else (getattr(self.workspace.pdk, "spef", None) or ""))
        )
        design_inputs = {
            **existing,
            "tech_lef": getattr(self.workspace.pdk, "tech", None) or "",
            "lef": list(getattr(self.workspace.pdk, "lefs", None) or []),
            "lib": list(getattr(self.workspace.pdk, "libs", None) or []),
            "def": self.input_def or "",
            "verilog": self.input_verilog or "",
            "sdc": step_tcl_path(self.workspace, self.step) or "",
            "spef": spef,
            "sta_config": sta_config or "",
            "rcx_config": rcx_config or "",
            "rcx_pdk": str(getattr(self.workspace.pdk, "name", "") or ""),
            "work_dir": Path(self.result_dir) / "native_sta",
            "thread_number": int(getattr(params, "num_threads", 2) or 2),
            "max_paths": 20,
        }
        if spef_rc:
            design_inputs.setdefault("timing_mode", "complete")
        return design_inputs

    def _log_path(self, *, mode: DreamplaceRunMode) -> str:
        log_name = {
            DreamplaceRunMode.PLACEMENT: "dreamplace_placement.log",
            DreamplaceRunMode.DIFF_OPT: "dreamplace_diff_opt.log",
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

            if mode is DreamplaceRunMode.DIFF_OPT:
                from .diff_opt import finalize_diff_opt

                ppa = finalize_diff_opt(engine)
            if place_io_engine in {"openroad", "ecc"}:
                if self.output_def:
                    engine.write_back(str(self.output_def))
                if place_io_engine in {"openroad", "ecc"} and self.output_verilog:
                    engine.write_verilog(self.output_verilog)

            return True

    def run_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.PLACEMENT)

    def run_diff_opt(self) -> bool:
        return self._run(mode=DreamplaceRunMode.DIFF_OPT)

    def run_diff_sizing(self) -> bool:
        return self._run(mode=DreamplaceRunMode.DIFF_SIZING)

    def run_macro_placement(self) -> bool:
        return self._run(mode=DreamplaceRunMode.MACRO_PLACEMENT)

    def run_legalization(self) -> bool:
        if self.step.name not in _LEGALIZE_OWNERS:
            return False
        return self._run(mode=DreamplaceRunMode.LEGALIZATION)


__all__ = ["DreamplaceModule", "DreamplaceRunMode"]
