#!/usr/bin/env python

import hashlib
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.utility.path import optional_path, path_text

_LEGALIZE_OWNERS = frozenset(
    {
        StepEnum.LEGALIZATION.value,
        StepEnum.TIMING_OPT.value,
    }
)


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

    def _build_params(self, params_cls, *, legalize_only: bool):
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

        if legalize_only:
            params.global_place_flag = 0
            params.legalize_flag = 1
            params.enable_fillers = 0
            params.random_center_init_flag = 0
            params.auto_adjust_bins = 1

        return params

    def _log_path(self, *, legalize_only: bool) -> str:
        log_name = "dreamplace_legalization.log" if legalize_only else "dreamplace_placement.log"
        return os.path.join(self.result_dir, log_name)

    def _file_handler_path(self, *, legalize_only: bool) -> str:
        if legalize_only and self.step.name != StepEnum.LEGALIZATION.value:
            return self._log_path(legalize_only=True)
        return str(self.step.log.file or self._log_path(legalize_only=legalize_only))

    @contextmanager
    def _configure_root_logging(self, *, legalize_only: bool):
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        log_file = self._file_handler_path(legalize_only=legalize_only)
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

    def _run(self, *, legalize_only: bool) -> bool:
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine

        with self._configure_root_logging(legalize_only=legalize_only):
            params = self._build_params(Params, legalize_only=legalize_only)

            engine = PlacementEngine(params)
            engine.setup_rawdb(ecc_module=self.ecc_module)
            ppa = engine.run()

            if ppa.get("hpwl") == float("inf"):
                _write_parameter_runtime_report(self.workspace, params, engine_succeeded=False)
                LOGGER = logging.getLogger(__name__)
                LOGGER.error("dreamplace failed for %s", self.step.name)
                return False

            _write_parameter_runtime_report(self.workspace, params, engine_succeeded=True)
            return True

    def run_placement(self) -> bool:
        return self._run(legalize_only=False)

    def run_legalization(self) -> bool:
        if self.step.name not in _LEGALIZE_OWNERS:
            return False
        return self._run(legalize_only=True)


__all__ = ["DreamplaceModule"]


def _write_parameter_runtime_report(
    workspace: Workspace, params, *, engine_succeeded: bool = False
) -> None:
    """Record the selected candidate knob at the native DreamPlace boundary."""
    report_path = Path(workspace.directory) / "analysis" / "parameter_runtime_report.v1.json"
    materialization_path = (
        Path(workspace.directory) / "analysis" / "candidate_materialization.v1.json"
    )
    if not materialization_path.is_file():
        return
    try:
        materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
        patch = materialization["patch"][0]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return
    knob_id = patch.get("knob_id")
    key_by_knob = {
        "place.target_density": ("target_density", "dreamplace.density_objective"),
        "place.target_overflow": ("stop_overflow", "dreamplace.overflow_predicate"),
        "place.cell_padding_x": ("cell_padding_x", "dreamplace.cell_size_expansion"),
        "place.routability_opt": ("routability_opt_flag", "dreamplace.routability_branch"),
        "place.density_weight": ("density_weight", "dreamplace.density_preconditioner"),
    }
    if knob_id not in key_by_knob:
        return
    key, consumer_id = key_by_knob[knob_id]
    value = getattr(params, key, None)
    status = "used" if value is not None and engine_succeeded else "unknown"
    branch_round_count = None
    if knob_id == "place.routability_opt":
        branch_round_count = _routability_branch_round_count(workspace)
        if value in (False, 0):
            status = "not_activated"
        elif not engine_succeeded:
            status = "unknown"
        else:
            status = "used" if branch_round_count else "not_activated"
    evidence = {
        "consumer_id": consumer_id,
        "outcome": "entered" if status == "used" else "evaluated",
        "evidence_ref": "analysis/parameter_runtime_report.v1.json",
    }
    evidence["evidence_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    report = {
        "application_status": "applied" if value is not None else "unknown",
        "effective_initial": {
            "value": value,
            "unit": "dbu" if knob_id.endswith("cell_padding_x") else "ratio",
        },
        "effective_final": {
            "value": value,
            "unit": "dbu" if knob_id.endswith("cell_padding_x") else "ratio",
        },
        "activation": {"status": status, "consumers": [evidence] if status != "unknown" else []},
        "transitions": [],
    }
    if knob_id == "place.routability_opt":
        report["consumer_observation"] = {
            "branch_round_count": branch_round_count,
            "evidence_complete": isinstance(branch_round_count, int),
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(temporary, report_path)


def _routability_branch_round_count(workspace: Workspace) -> int | None:
    """Count native routability rounds emitted by the placement engine."""
    log_path = Path(workspace.directory) / "place_dreamplace" / "log" / "place.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return len(re.findall(r"routability optimization round \d+:", text))
