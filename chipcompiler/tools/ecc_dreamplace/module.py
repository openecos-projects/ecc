#!/usr/bin/env python

import hashlib
import json
import logging
import os
import sys
from contextlib import contextmanager, suppress
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
DREAMPLACE_RUNTIME_REPORT_REVISION = "ecc.dreamplace.parameter_runtime_report.v2"


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
            with _capture_native_runtime() as native_runtime_probe:
                ppa = engine.run()
            engine.native_runtime_probe = native_runtime_probe

            if ppa.get("hpwl") == float("inf"):
                if not legalize_only:
                    _write_parameter_runtime_report(
                        self.workspace, engine.params, engine=engine, ppa=ppa
                    )
                LOGGER = logging.getLogger(__name__)
                LOGGER.error("dreamplace failed for %s", self.step.name)
                return False

            if not legalize_only:
                _write_parameter_runtime_report(
                    self.workspace,
                    engine.params,
                    engine=engine,
                    ppa=ppa,
                    engine_succeeded=True,
                )
            return True

    def run_placement(self) -> bool:
        return self._run(legalize_only=False)

    def run_legalization(self) -> bool:
        if self.step.name not in _LEGALIZE_OWNERS:
            return False
        return self._run(legalize_only=True)


__all__ = ["DreamplaceModule"]


def _runtime_unit(knob_id: str) -> str:
    if knob_id.endswith("routability_opt"):
        return "boolean"
    if knob_id.endswith("cell_padding_x"):
        return "dbu"
    if knob_id.endswith("density_weight"):
        return "objective_weight"
    return "ratio"


def _write_parameter_runtime_report(
    workspace: Workspace,
    params,
    *,
    engine=None,
    ppa: dict | None = None,
    engine_succeeded: bool = False,
) -> None:
    """Record the selected candidate knob at the native DreamPlace boundary."""
    patch = _candidate_patch(workspace)
    if patch is None:
        return
    knob_id = patch.get("knob_id")
    consumer_by_knob = {
        "place.target_density": "dreamplace.density_objective",
        "place.target_overflow": "dreamplace.overflow_predicate",
        "place.cell_padding_x": "dreamplace.cell_size_expansion",
        "place.routability_opt": "dreamplace.routability_branch",
        "place.density_weight": "dreamplace.density_preconditioner",
    }
    if knob_id not in consumer_by_knob:
        return
    consumer_id = consumer_by_knob[knob_id]
    observation = _consumer_observation(workspace, knob_id, patch.get("value"), params, engine, ppa)
    value = _effective_value(knob_id, params, observation)
    status = _activation_status(knob_id, value, observation, engine_succeeded=engine_succeeded)
    outcome = "evaluated" if knob_id == "place.target_overflow" or status != "used" else "entered"
    evidence_payload = {
        "consumer_id": consumer_id,
        "outcome": outcome,
        "consumer_observation": observation,
    }
    evidence = {
        "consumer_id": consumer_id,
        "outcome": outcome,
        "evidence_ref": "analysis/parameter_runtime_report.v1.json",
        "evidence_sha256": _payload_sha256(evidence_payload),
    }
    report = {
        "knob_id": knob_id,
        "requested_value": patch.get("value"),
        "tool": {
            "name": "DREAMPlace",
            "revision": DREAMPLACE_RUNTIME_REPORT_REVISION,
            "source_sha256": _source_sha256(),
        },
        "application_status": "applied" if value is not None else "unknown",
        "effective_initial": {"value": value, "unit": _runtime_unit(knob_id)},
        "effective_final": {"value": value, "unit": _runtime_unit(knob_id)},
        "activation": {"status": status, "consumers": [evidence] if status != "unknown" else []},
        "transitions": (
            _runtime_transitions(knob_id, patch.get("value"), value, evidence)
            if status == "used"
            else []
        ),
        "consumer_observation": observation,
    }
    report_path = Path(workspace.directory) / "analysis" / "parameter_runtime_report.v1.json"
    _write_json_atomic(report_path, report)


def _candidate_patch(workspace: Workspace) -> dict | None:
    path = Path(workspace.directory) / "analysis" / "candidate_materialization.v1.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["patch"][0]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(temporary, path)


def _consumer_observation(workspace, knob_id, requested, params, engine, ppa) -> dict:
    ppa = ppa if isinstance(ppa, dict) else {}
    iterations = ppa.get("iteration")
    valid_iterations = type(iterations) is int and iterations > 0
    if knob_id == "place.target_density":
        data = getattr(
            getattr(getattr(engine, "placer", None), "data_collections", None),
            "target_density",
            None,
        )
        tensor_value = _scalar_value(data)
        effective = _scalar_value(getattr(params, "target_density", None))
        return {
            "requested_target_density": requested,
            "effective_target_density": effective,
            "density_tensor_value": tensor_value,
            "placement_iteration_count": iterations,
            "evidence_complete": valid_iterations and tensor_value == effective,
        }
    if knob_id == "place.target_overflow":
        overflows = _native_overflow_values(engine)
        threshold = _scalar_value(getattr(params, "stop_overflow", None))
        minimum = min(overflows) if overflows else None
        return {
            "effective_stop_overflow": threshold,
            "final_overflow": _scalar_value(ppa.get("overflow")),
            "placement_iteration_count": iterations,
            "comparison_count": len(overflows),
            "minimum_observed_overflow": minimum,
            "threshold_reached": minimum <= threshold
            if minimum is not None and threshold is not None
            else None,
            "evidence_complete": valid_iterations and bool(overflows) and threshold is not None,
        }
    if knob_id == "place.cell_padding_x":
        placedb = getattr(engine, "placedb", None)
        effective = _scalar_value(getattr(placedb, "cell_padding_x", None))
        site_width_dbu = _scalar_value(getattr(placedb, "origin_site_width", None))
        if effective is not None and site_width_dbu is not None and site_width_dbu > 0:
            effective = round(effective * site_width_dbu)
        else:
            effective = None
        movable = getattr(placedb, "num_movable_nodes", None)
        return {
            "requested_padding_dbu": requested,
            "effective_padding_dbu": effective,
            "movable_node_count": movable,
            "placement_iteration_count": iterations,
            "evidence_complete": valid_iterations
            and effective is not None
            and type(movable) is int,
        }
    if knob_id == "place.density_weight":
        probe = _native_runtime_probe(engine)
        initializations = probe.get("density_weight_initializations", [])
        updates = probe.get("density_weight_updates", [])
        initial = initializations[0] if initializations else None
        final = (
            updates[-1]["after"] if updates else initializations[-1] if initializations else None
        )
        return {
            "configured_density_weight": _scalar_value(getattr(params, "density_weight", None)),
            "internal_initial_density_weight": initial,
            "density_weight_updates": updates,
            "density_weight_update_count": len(updates),
            "final_internal_density_weight": final,
            "final_objective": _scalar_value(ppa.get("objective")),
            "placement_iteration_count": iterations,
            "evidence_complete": valid_iterations
            and initial is not None
            and _scalar_value(ppa.get("objective")) is not None,
        }
    rounds = _native_runtime_probe(engine).get("routability_branch_round_count")
    return {"branch_round_count": rounds, "evidence_complete": isinstance(rounds, int)}


def _effective_value(knob_id: str, params, observation: dict):
    if knob_id == "place.target_density":
        return observation["effective_target_density"]
    if knob_id == "place.cell_padding_x":
        return observation["effective_padding_dbu"]
    key = {
        "place.target_overflow": "stop_overflow",
        "place.routability_opt": "routability_opt_flag",
        "place.density_weight": "density_weight",
    }[knob_id]
    return _scalar_value(getattr(params, key, None))


def _activation_status(knob_id: str, value, observation: dict, *, engine_succeeded: bool) -> str:
    if not engine_succeeded or not observation.get("evidence_complete"):
        return "unknown"
    if knob_id == "place.routability_opt" and value in (False, 0):
        return "not_activated"
    if knob_id == "place.routability_opt" and not observation.get("branch_round_count"):
        return "not_activated"
    if knob_id == "place.cell_padding_x" and value == 0:
        return "not_activated"
    return "used"


def _runtime_transitions(knob_id: str, requested, effective, evidence: dict) -> list[dict]:
    if knob_id != "place.target_density" or not isinstance(requested, (int, float)):
        return []
    if not isinstance(effective, (int, float)) or effective <= requested:
        return []
    return [
        {
            "sequence": 0,
            "from": "materialized",
            "to": "overridden",
            "value": effective,
            "reason": "DREAMPlace utilization lower bound",
            "rule_id": "dreamplace.target_density.utilization_floor",
            "evidence_ref": evidence["evidence_ref"],
            "evidence_sha256": evidence["evidence_sha256"],
        }
    ]


def _scalar_value(value):
    with suppress(AttributeError):
        value = value.item()
    return value if type(value) in {bool, int, float} else None


def _payload_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _source_sha256() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _native_runtime_probe(engine) -> dict:
    probe = getattr(engine, "native_runtime_probe", None)
    return probe if isinstance(probe, dict) else {}


def _native_overflow_values(engine) -> list[float]:
    metrics = getattr(engine, "metrics", None)
    values = metrics.get("overflow", []) if isinstance(metrics, dict) else []
    return [value for item in values if (value := _scalar_value(item)) is not None]


def _native_numeric(value):
    for operation in ("detach", "cpu", "tolist"):
        with suppress(AttributeError):
            value = getattr(value, operation)()
    if type(value) in {int, float}:
        return value
    if isinstance(value, list) and value and all(type(item) in {int, float} for item in value):
        return value
    return None


@contextmanager
def _capture_native_runtime():
    from dreamplace.PlaceObj import PlaceObj

    probe = {
        "density_weight_initializations": [],
        "density_weight_updates": [],
        "routability_branch_round_count": 0,
    }
    original_init = PlaceObj.__init__

    def observed_init(model, *args, **kwargs):
        original_init(model, *args, **kwargs)
        _observe_native_model(model, probe)

    PlaceObj.__init__ = observed_init
    try:
        yield probe
    finally:
        PlaceObj.__init__ = original_init


def _observe_native_model(model, probe: dict) -> None:
    initialize = model.initialize_density_weight

    def observed_initialize(*args, **kwargs):
        result = initialize(*args, **kwargs)
        if (value := _native_numeric(result)) is not None:
            probe["density_weight_initializations"].append(value)
        return result

    model.initialize_density_weight = observed_initialize
    operations = model.op_collections
    update = getattr(operations, "update_density_weight_op", None)
    if callable(update):

        def observed_update(*args, **kwargs):
            before = _native_numeric(model.density_weight)
            result = update(*args, **kwargs)
            after = _native_numeric(model.density_weight)
            probe["density_weight_updates"].append(
                {
                    "sequence": len(probe["density_weight_updates"]),
                    "before": before,
                    "after": after,
                }
            )
            return result

        operations.update_density_weight_op = observed_update
    adjust_area = getattr(operations, "adjust_node_area_op", None)
    if callable(adjust_area):

        def observed_adjust_area(*args, **kwargs):
            probe["routability_branch_round_count"] += 1
            return adjust_area(*args, **kwargs)

        operations.adjust_node_area_op = observed_adjust_area
