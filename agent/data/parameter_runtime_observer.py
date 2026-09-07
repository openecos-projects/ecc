"""Agent-owned DREAMPlace runtime observation for controlled candidates."""

import math
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from threading import RLock, get_ident
from typing import Any

from .candidate_artifacts import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_path,
    write_json_atomic,
)

DREAMPLACE_OBSERVER_REVISION = "ecc.agent.dreamplace_parameter_observer.v1"
RUNTIME_REPORT_REF = "analysis/parameter_runtime_report.v1.json"

# ponytail: serialize same-process observers; use permanent thread-local hooks
# if parallel flow throughput matters.
_OBSERVATION_LOCK = RLock()

DREAMPLACE_KNOBS = frozenset(
    {
        "place.target_density",
        "place.target_overflow",
        "place.cell_padding_x",
        "place.routability_opt",
        "place.density_weight",
    }
)


@dataclass
class DreamplaceRecorder:
    patch: dict[str, Any]
    engine: Any = None
    model: Any = None
    ppa: dict[str, Any] = field(default_factory=dict)
    placement_depth: int = 0
    probe: dict[str, Any] = field(
        default_factory=lambda: {
            "density_operator_call_count": 0,
            "density_weight_initializations": [],
            "density_weight_updates": [],
            "nonlinear_place_call_count": 0,
            "place_object_count": 0,
            "routability_branch_round_count": 0,
            "routability_operator_constructed": False,
            "stop_overflow_read_count": 0,
        }
    )


def run_with_parameter_observation(
    workspace: Any,
    step: Any,
    materialization: dict[str, Any] | None,
    invoke: Callable[[], Any],
) -> Any:
    """Run a candidate step and persist runtime evidence without changing its result."""
    if materialization is None:
        return invoke()
    patch = materialization["patch"][0]
    knob_id = patch["knob_id"]
    if knob_id not in DREAMPLACE_KNOBS:
        from .floorplan_parameter_observer import FLOORPLAN_KNOBS

        if knob_id not in FLOORPLAN_KNOBS:
            return invoke()

    if knob_id in DREAMPLACE_KNOBS:
        with _capture_dreamplace(patch) as recorder:
            return _invoke_and_record(
                workspace,
                invoke,
                lambda succeeded: _build_dreamplace_report(
                    patch,
                    recorder.engine,
                    recorder.ppa,
                    _final_probe(recorder),
                    engine_succeeded=succeeded,
                ),
            )

    from .floorplan_parameter_observer import (
        build_floorplan_report,
        capture_floorplan,
        step_path,
    )

    with capture_floorplan(patch) as boundary:
        return _invoke_and_record(
            workspace,
            invoke,
            lambda succeeded: build_floorplan_report(
                patch,
                boundary,
                step_path(step, "feature", "db"),
                engine_succeeded=succeeded,
            ),
        )


def _invoke_and_record(
    workspace: Any,
    invoke: Callable[[], Any],
    build_report: Callable[[bool], dict[str, Any]],
) -> Any:
    try:
        result = invoke()
    except BaseException:
        _persist_report(workspace, build_report, engine_succeeded=False)
        raise
    _persist_report(workspace, build_report, engine_succeeded=bool(result))
    return result


def _persist_report(
    workspace: Any,
    build_report: Callable[[bool], dict[str, Any]],
    *,
    engine_succeeded: bool,
) -> None:
    try:
        report = build_report(engine_succeeded)
        write_json_atomic(Path(workspace.directory) / RUNTIME_REPORT_REF, report)
    except Exception:
        logger = getattr(workspace, "logger", None)
        if logger is not None:
            logger.exception("Failed to persist parameter runtime evidence")


@contextmanager
def _capture_dreamplace(
    patch: dict[str, Any],
) -> Iterator[DreamplaceRecorder]:
    from dreamplace.macroPlaceDB import MacroPlaceDB
    from dreamplace.Params import Params
    from dreamplace.PlaceObj import PlaceObj
    from dreamplace.Placer import PlacementEngine

    recorder = DreamplaceRecorder(patch=patch)
    with _OBSERVATION_LOCK, ExitStack() as stack:
        _patch_method(
            stack,
            PlacementEngine,
            "run",
            partial(_observe_placement_run, recorder),
        )
        _patch_method(
            stack,
            PlacementEngine,
            "place",
            partial(_observe_placement_call, recorder),
        )
        if patch["knob_id"] == "place.target_overflow":
            _patch_method(
                stack,
                Params,
                "__getattribute__",
                partial(_observe_parameter_read, recorder),
            )
        if patch["knob_id"] == "place.cell_padding_x":
            _patch_method(
                stack,
                MacroPlaceDB,
                "_apply_cell_padding",
                partial(_observe_cell_padding, recorder),
            )
        if patch["knob_id"] in {
            "place.target_density",
            "place.density_weight",
            "place.routability_opt",
        }:
            _patch_method(
                stack,
                PlaceObj,
                "__init__",
                partial(_observe_place_object_init, recorder, stack),
            )
        yield recorder


def _patch_method(
    stack: ExitStack,
    owner: Any,
    name: str,
    observer: Callable[..., Any],
) -> None:
    original = getattr(owner, name)
    owner_thread = get_ident()

    @wraps(original)
    def observed(*args, **kwargs):
        if get_ident() != owner_thread:
            return original(*args, **kwargs)
        return observer(original, *args, **kwargs)

    previous = vars(owner).get(name, _MISSING)
    setattr(owner, name, observed)
    stack.callback(_restore_attribute, owner, name, previous)


_MISSING = object()


def _restore_attribute(owner: Any, name: str, previous: Any) -> None:
    if previous is _MISSING:
        delattr(owner, name)
    else:
        setattr(owner, name, previous)


def _observe_placement_run(recorder, original, engine, *args, **kwargs):
    try:
        result = original(engine, *args, **kwargs)
    finally:
        recorder.engine = engine
    if isinstance(result, dict):
        recorder.ppa = dict(result)
    return result


def _observe_placement_call(recorder, original, engine, *args, **kwargs):
    recorder.probe["nonlinear_place_call_count"] += 1
    recorder.placement_depth += 1
    try:
        return original(engine, *args, **kwargs)
    finally:
        recorder.placement_depth -= 1


def _observe_parameter_read(recorder, original, params, name):
    value = original(params, name)
    if recorder.placement_depth and name == "stop_overflow":
        recorder.probe["stop_overflow_read_count"] += 1
    return value


def _observe_cell_padding(recorder, original, placedb, params, *args, **kwargs):
    normalized = _scalar_value(getattr(params, "cell_padding_x", None))
    result = original(placedb, params, *args, **kwargs)
    recorder.probe["cell_padding"] = {
        "normalized_padding_dbu": normalized,
        "effective_padding_dbu": _scalar_value(getattr(placedb, "cell_padding_x", None)),
        "geometry_apply_count": 1,
    }
    return result


def _observe_place_object_init(
    recorder,
    stack,
    original,
    model,
    *args,
    **kwargs,
):
    result = original(model, *args, **kwargs)
    recorder.model = model
    recorder.probe["place_object_count"] += 1
    _observe_native_model(model, recorder, stack)
    return result


def _observe_native_model(
    model: Any,
    recorder: DreamplaceRecorder,
    stack: ExitStack,
) -> None:
    knob_id = recorder.patch["knob_id"]
    operations = model.op_collections
    if knob_id == "place.target_density":
        for name in ("density_op", "fence_region_density_merged_op"):
            operation = getattr(operations, name, None)
            if callable(operation):
                _patch_method(
                    stack,
                    operations,
                    name,
                    partial(_observe_density_operator, recorder),
                )
    elif knob_id == "place.density_weight":
        _patch_method(
            stack,
            model,
            "initialize_density_weight",
            partial(_observe_density_weight_initialization, recorder),
        )
        if callable(getattr(operations, "update_density_weight_op", None)):
            _patch_method(
                stack,
                operations,
                "update_density_weight_op",
                partial(_observe_density_weight_update, recorder, model),
            )
    elif knob_id == "place.routability_opt":
        adjust_area = getattr(operations, "adjust_node_area_op", None)
        recorder.probe["routability_operator_constructed"] = callable(adjust_area)
        if callable(adjust_area):
            _patch_method(
                stack,
                operations,
                "adjust_node_area_op",
                partial(_observe_routability_round, recorder),
            )


def _observe_density_operator(recorder, original, *args, **kwargs):
    recorder.probe["density_operator_call_count"] += 1
    return original(*args, **kwargs)


def _observe_density_weight_initialization(recorder, original, *args, **kwargs):
    result = original(*args, **kwargs)
    if (value := _native_value(result)) is not None:
        recorder.probe["density_weight_initializations"].append(value)
    return result


def _observe_density_weight_update(recorder, model, original, *args, **kwargs):
    before = _native_value(model.density_weight)
    result = original(*args, **kwargs)
    recorder.probe["density_weight_updates"].append(
        {
            "sequence": len(recorder.probe["density_weight_updates"]),
            "before": before,
            "after": _native_value(model.density_weight),
        }
    )
    return result


def _observe_routability_round(recorder, original, *args, **kwargs):
    recorder.probe["routability_branch_round_count"] += 1
    return original(*args, **kwargs)


def _final_probe(recorder: DreamplaceRecorder) -> dict[str, Any]:
    probe = dict(recorder.probe)
    if recorder.model is not None:
        probe["final_internal_density_weight"] = _native_value(
            getattr(recorder.model, "density_weight", None)
        )
    return probe


def _build_dreamplace_report(
    patch: dict[str, Any],
    engine: Any,
    ppa: dict[str, Any] | None,
    probe: dict[str, Any],
    *,
    engine_succeeded: bool,
) -> dict[str, Any]:
    knob_id = patch["knob_id"]
    params = getattr(engine, "params", None)
    ppa = ppa if isinstance(ppa, dict) else {}
    observation = _dreamplace_observation(knob_id, patch["value"], params, engine, ppa, probe)
    initial, final, unit = _dreamplace_effective_values(knob_id, params, observation)
    status = _dreamplace_activation_status(
        knob_id, initial, observation, engine_succeeded=engine_succeeded
    )
    outcome = "evaluated" if knob_id == "place.target_overflow" else "entered"
    if status == "not_activated":
        outcome = "evaluated"
    evidence = _consumer_evidence(knob_id, outcome, observation)
    return {
        "knob_id": knob_id,
        "requested_value": patch["value"],
        "tool": {
            "name": "DREAMPlace",
            "revision": DREAMPLACE_OBSERVER_REVISION,
            "source_sha256": sha256_path(Path(__file__)),
        },
        "application_status": (
            "applied" if engine_succeeded and initial is not None else "unknown"
        ),
        "effective_initial": {"value": initial, "unit": unit},
        "effective_final": {"value": final, "unit": unit},
        "activation": {
            "status": status,
            "consumers": [evidence] if status in {"used", "not_activated"} else [],
        },
        "transitions": _dreamplace_transitions(
            knob_id, patch["value"], initial, evidence, observation
        )
        if status == "used"
        else [],
        "consumer_observation": observation,
    }


def _consumer_evidence(knob_id: str, outcome: str, observation: dict) -> dict:
    consumer_id = _dreamplace_consumer(knob_id)
    payload = {
        "consumer_id": consumer_id,
        "outcome": outcome,
        "consumer_observation": observation,
    }
    return {
        "consumer_id": consumer_id,
        "outcome": outcome,
        "evidence_ref": RUNTIME_REPORT_REF,
        "evidence_sha256": sha256_bytes(canonical_json_bytes(payload)),
    }


def _dreamplace_observation(knob_id, requested, params, engine, ppa, probe) -> dict:
    iterations = ppa.get("iteration")
    handlers = {
        "place.target_density": _target_density_observation,
        "place.target_overflow": _target_overflow_observation,
        "place.cell_padding_x": _cell_padding_observation,
        "place.density_weight": _density_weight_observation,
        "place.routability_opt": _routability_observation,
    }
    return handlers[knob_id](requested, params, engine, ppa, probe, iterations)


def _target_density_observation(requested, params, engine, _ppa, probe, iterations):
    tensor = _scalar_value(
        getattr(
            getattr(getattr(engine, "placer", None), "data_collections", None),
            "target_density",
            None,
        )
    )
    effective = _scalar_value(getattr(params, "target_density", None))
    calls = probe.get("density_operator_call_count", 0)
    return {
        "requested_target_density": requested,
        "effective_target_density": effective,
        "density_tensor_value": tensor,
        "density_operator_call_count": calls,
        "placement_iteration_count": iterations,
        "evidence_complete": _valid_iterations(iterations)
        and _same_number(tensor, effective)
        and calls > 0,
        "lifecycle": _lifecycle(
            ("adopted", effective, "ratio", "direct_python_runtime"),
            ("consumed", tensor, "ratio", "direct_python_runtime"),
        ),
    }


def _target_overflow_observation(_requested, params, engine, ppa, probe, iterations):
    overflows = _native_overflow_values(engine)
    threshold = _scalar_value(getattr(params, "stop_overflow", None))
    read_count = probe.get("stop_overflow_read_count", 0)
    final = _scalar_value(ppa.get("overflow"))
    return {
        "effective_stop_overflow": threshold,
        "final_overflow": final,
        "placement_iteration_count": iterations,
        "predicate_owner_call_count": probe.get("nonlinear_place_call_count", 0),
        "threshold_read_count": read_count,
        "observed_overflow_count": len(overflows),
        "minimum_observed_overflow": min(overflows) if overflows else None,
        "threshold_reached": min(overflows) <= threshold
        if overflows and threshold is not None
        else None,
        "evidence_complete": _valid_iterations(iterations)
        and threshold is not None
        and read_count > 0,
        "lifecycle": _lifecycle(
            ("adopted", threshold, "ratio", "direct_python_runtime"),
            ("consumed", threshold, "ratio", "direct_python_runtime"),
            ("realized", final, "overflow", "post_run_state"),
        ),
    }


def _cell_padding_observation(requested, params, engine, _ppa, probe, iterations):
    placedb = getattr(engine, "placedb", None)
    padding = probe.get("cell_padding", {})
    effective_dbu = _scalar_value(padding.get("effective_padding_dbu"))
    restored = _scalar_value(getattr(params, "cell_padding_x", None))
    movable = getattr(placedb, "num_movable_nodes", None)
    return {
        "requested_padding_dbu": requested,
        "normalized_padding_dbu": padding.get("normalized_padding_dbu"),
        "effective_padding_dbu": effective_dbu,
        "effective_padding_sites": _scalar_value(getattr(placedb, "cell_padding_x", None)),
        "post_legalization_padding_sites": restored,
        "representation_restored": restored == 0,
        "geometry_apply_count": padding.get("geometry_apply_count", 0),
        "movable_node_count": movable,
        "placement_iteration_count": iterations,
        "evidence_complete": _valid_iterations(iterations)
        and effective_dbu is not None
        and type(movable) is int
        and padding.get("geometry_apply_count", 0) > 0,
        "lifecycle": _lifecycle(
            (
                "normalized",
                padding.get("normalized_padding_dbu"),
                "dbu",
                "direct_python_runtime",
            ),
            ("consumed", effective_dbu, "dbu", "direct_python_runtime"),
            ("restored", restored, "internal_site", "post_run_state"),
        ),
    }


def _density_weight_observation(_requested, params, _engine, ppa, probe, iterations):
    initializations = probe.get("density_weight_initializations", [])
    updates = probe.get("density_weight_updates", [])
    initial = initializations[0] if initializations else None
    final = probe.get("final_internal_density_weight")
    if final is None:
        final = updates[-1]["after"] if updates else initial
    objective = _scalar_value(ppa.get("objective"))
    return {
        "configured_density_weight": _scalar_value(getattr(params, "density_weight", None)),
        "internal_initial_density_weight": initial,
        "density_weight_updates": updates,
        "density_weight_update_count": len(updates),
        "final_internal_density_weight": final,
        "final_objective": objective,
        "placement_iteration_count": iterations,
        "evidence_complete": _valid_iterations(iterations)
        and _runtime_scalar(initial) is not None
        and _runtime_scalar(final) is not None
        and objective is not None,
        "lifecycle": _lifecycle(
            ("adopted", initial, "internal_objective_weight", "direct_python_runtime"),
            ("evolved", final, "internal_objective_weight", "direct_python_runtime"),
        ),
    }


def _routability_observation(_requested, params, _engine, _ppa, probe, iterations):
    rounds = probe.get("routability_branch_round_count")
    configured = _scalar_value(getattr(params, "routability_opt_flag", None))
    place_objects = probe.get("place_object_count", 0)
    return {
        "configured_routability_opt": configured,
        "operator_constructed": probe.get("routability_operator_constructed", False),
        "branch_round_count": rounds,
        "place_object_count": place_objects,
        "placement_iteration_count": iterations,
        "evidence_complete": type(rounds) is int and place_objects > 0,
        "lifecycle": _lifecycle(
            ("adopted", configured, "boolean", "direct_python_runtime"),
            ("consumed", rounds, "branch_round_count", "direct_python_runtime"),
        ),
    }


def _dreamplace_effective_values(knob_id, params, observation) -> tuple[Any, Any, str]:
    if knob_id == "place.target_density":
        value = observation["effective_target_density"]
        return value, value, "ratio"
    if knob_id == "place.target_overflow":
        value = observation["effective_stop_overflow"]
        return value, value, "ratio"
    if knob_id == "place.cell_padding_x":
        value = observation["effective_padding_dbu"]
        return value, value, "dbu"
    if knob_id == "place.density_weight":
        return (
            _runtime_scalar(observation["internal_initial_density_weight"]),
            _runtime_scalar(observation["final_internal_density_weight"]),
            "internal_objective_weight",
        )
    value = _scalar_value(getattr(params, "routability_opt_flag", None))
    return value, value, "boolean"


def _dreamplace_activation_status(
    knob_id: str,
    effective: Any,
    observation: dict[str, Any],
    *,
    engine_succeeded: bool,
) -> str:
    if not engine_succeeded or not observation.get("evidence_complete"):
        return "unknown"
    if knob_id == "place.routability_opt" and (
        effective in (False, 0) or not observation.get("branch_round_count")
    ):
        return "not_activated"
    if knob_id == "place.cell_padding_x" and effective == 0:
        return "not_activated"
    return "used"


def _dreamplace_transitions(knob_id, requested, effective, evidence, observation):
    if (
        knob_id == "place.target_density"
        and isinstance(effective, (int, float))
        and effective > requested
    ):
        return [_transition("materialized", "overridden", effective, evidence)]
    normalized = observation.get("normalized_padding_dbu")
    if knob_id == "place.cell_padding_x" and (normalized is not None and effective != normalized):
        return [_transition("normalized", "clamped", effective, evidence)]
    return []


def _transition(source: str, target: str, value: Any, evidence: dict) -> dict:
    transition = {
        "sequence": 0,
        "from": source,
        "to": target,
        "value": value,
        "reason": {
            "overridden": "DREAMPlace utilization lower bound",
            "clamped": "DREAMPlace movable-area padding cap",
        }[target],
        "evidence_ref": RUNTIME_REPORT_REF,
        "evidence_sha256": evidence["evidence_sha256"],
    }
    if target == "overridden":
        transition["rule_id"] = "dreamplace.target_density.utilization_floor"
    return transition


def _dreamplace_consumer(knob_id: str) -> str:
    return {
        "place.target_density": "dreamplace.density_objective",
        "place.target_overflow": "dreamplace.overflow_predicate",
        "place.cell_padding_x": "dreamplace.cell_size_expansion",
        "place.routability_opt": "dreamplace.routability_branch",
        "place.density_weight": "dreamplace.density_preconditioner",
    }[knob_id]


def _lifecycle(*events: tuple[str, Any, str, str]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": sequence,
            "phase": phase,
            "value": value,
            "unit": unit,
            "evidence_kind": evidence_kind,
        }
        for sequence, (phase, value, unit, evidence_kind) in enumerate(events)
    ]


def _native_overflow_values(engine: Any) -> list[float]:
    metrics = getattr(engine, "metrics", None)
    values = metrics.get("overflow", []) if isinstance(metrics, dict) else []
    return [value for item in values if (value := _scalar_value(item)) is not None]


def _native_value(value: Any):
    for operation in ("detach", "cpu", "tolist"):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            value = getattr(value, operation)()
    if isinstance(value, list):
        values = [_native_value(item) for item in value]
        return values[0] if len(values) == 1 else values
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        value = value.item()
    return _finite_scalar(value)


def _scalar_value(value: Any):
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        value = value.item()
    return _finite_scalar(value)


def _finite_scalar(value: Any):
    if type(value) is bool or type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    return None


def _runtime_scalar(value: Any):
    return value if type(value) in {int, float} and math.isfinite(value) else None


def _valid_iterations(value: Any) -> bool:
    return type(value) is int and value > 0


def _same_number(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
    )
