#!/usr/bin/env python

import hashlib
import json
from contextlib import contextmanager, suppress
from pathlib import Path

from chipcompiler.data import Workspace
from chipcompiler.utility.json import json_write

DREAMPLACE_RUNTIME_REPORT_REVISION = "ecc.dreamplace.parameter_runtime_report.v2"
_NATIVE_PROBE_KNOBS = frozenset(
    {
        "place.density_weight",
        "place.routability_opt",
    }
)


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
    workspace_dir = workspace.directory
    if workspace_dir is None:
        return
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
    observation = _consumer_observation(knob_id, patch.get("value"), params, engine, ppa)
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
    report_path = Path(workspace_dir) / "analysis" / "parameter_runtime_report.v1.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if not json_write(report_path, report, indent=None):
        raise OSError(f"Failed to write DreamPlace parameter runtime report: {report_path}")


def _candidate_patch(workspace: Workspace) -> dict | None:
    workspace_dir = workspace.directory
    if workspace_dir is None:
        return None
    path = Path(workspace_dir) / "analysis" / "candidate_materialization.v1.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["patch"][0]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _consumer_observation(knob_id, requested, params, engine, ppa) -> dict:
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
def _capture_native_runtime(workspace: Workspace):
    patch = _candidate_patch(workspace)
    if patch is None or patch.get("knob_id") not in _NATIVE_PROBE_KNOBS:
        yield {}
        return

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
