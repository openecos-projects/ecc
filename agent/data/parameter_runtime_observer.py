"""Agent-owned observation of the five controlled DREAMPlace parameters."""

import math
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from threading import RLock, get_ident
from typing import Any

from .candidate_artifacts import sha256_path, write_json_atomic
from .observed_callable import ObservedCallable

DREAMPLACE_OBSERVER_REVISION = "ecc.agent.dreamplace_parameter_observer.v2"
RUNTIME_REPORT_REF = "analysis/parameter_runtime_report.v2.json"
DREAMPLACE_KNOBS = frozenset(
    {
        "place.target_density",
        "place.target_overflow",
        "place.cell_padding_x",
        "place.routability_opt",
        "place.density_weight",
    }
)
# ponytail: serialize same-process observers; use thread-local hooks if throughput matters.
_OBSERVATION_LOCK = RLock()
_MISSING = object()


@dataclass
class DreamplaceRecorder:
    patch: dict[str, Any]
    engine: Any = None
    model: Any = None
    ppa: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(
        default_factory=lambda: {
            "density_operator_call_count": 0,
            "initialization_count": 0,
            "place_object_count": 0,
            "routability_branch_round_count": 0,
            "placement_completed": False,
        }
    )


def run_with_parameter_observation(workspace, step, materialization, invoke):
    if materialization is None:
        return invoke()
    patch = materialization["patch"][0]
    if patch["knob_id"] in DREAMPLACE_KNOBS:
        with _capture_dreamplace(patch) as recorder:
            return _invoke_and_record(
                workspace,
                invoke,
                lambda succeeded: _build_dreamplace_report(
                    patch,
                    recorder.engine,
                    recorder.ppa,
                    recorder.probe,
                    engine_succeeded=succeeded,
                ),
            )
    from .floorplan_parameter_observer import (
        FLOORPLAN_KNOBS,
        build_floorplan_report,
        capture_floorplan,
        step_path,
    )

    if patch["knob_id"] not in FLOORPLAN_KNOBS:
        return invoke()
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


def _invoke_and_record(workspace, invoke, build_report):
    try:
        result = invoke()
    except BaseException:
        _persist_report(workspace, build_report, engine_succeeded=False)
        raise
    _persist_report(workspace, build_report, engine_succeeded=bool(result))
    return result


def _persist_report(workspace, build_report, *, engine_succeeded):
    try:
        write_json_atomic(
            Path(workspace.directory) / RUNTIME_REPORT_REF, build_report(engine_succeeded)
        )
    except Exception:
        logger = getattr(workspace, "logger", None)
        if logger is not None:
            logger.exception("Failed to persist parameter runtime evidence")


@contextmanager
def _capture_dreamplace(patch: dict[str, Any]) -> Iterator[DreamplaceRecorder]:
    from dreamplace.macroPlaceDB import MacroPlaceDB
    from dreamplace.PlaceObj import PlaceObj
    from dreamplace.Placer import PlacementEngine

    recorder = DreamplaceRecorder(patch=patch)
    with _OBSERVATION_LOCK, ExitStack() as stack:
        _patch_method(stack, PlacementEngine, "run", partial(_observe_placement_run, recorder))
        _patch_method(stack, PlacementEngine, "place", partial(_observe_placement_call, recorder))
        if patch["knob_id"] == "place.cell_padding_x":
            _patch_method(
                stack, MacroPlaceDB, "_apply_cell_padding", partial(_observe_cell_padding, recorder)
            )
        if patch["knob_id"] in {
            "place.target_density",
            "place.density_weight",
            "place.routability_opt",
        }:
            _patch_method(
                stack, PlaceObj, "__init__", partial(_observe_place_object_init, recorder, stack)
            )
        yield recorder


def _patch_method(stack: ExitStack, owner: Any, name: str, observer: Callable) -> None:
    original = getattr(owner, name)
    owner_thread = get_ident()

    @wraps(original)
    def observed(*args, **kwargs):
        if get_ident() != owner_thread:
            return original(*args, **kwargs)
        return observer(original, *args, **kwargs)

    previous = vars(owner).get(name, _MISSING)
    replacement = observed if isinstance(owner, type) else ObservedCallable(observed, original)
    setattr(owner, name, replacement)
    stack.callback(_restore_attribute, owner, name, previous)


def _restore_attribute(owner, name, previous):
    if previous is _MISSING:
        delattr(owner, name)
    else:
        setattr(owner, name, previous)


def _observe_placement_run(recorder, original, engine, *args, **kwargs):
    recorder.engine = engine
    result = original(engine, *args, **kwargs)
    if isinstance(result, dict):
        recorder.ppa = dict(result)
    return result


def _observe_placement_call(recorder, original, engine, *args, **kwargs):
    recorder.engine = engine
    placedb = getattr(engine, "placedb", None)
    area = _scalar_value(getattr(placedb, "total_movable_node_area", None))
    space = _scalar_value(getattr(placedb, "total_space_area", None))
    if area is not None and space is not None and space > 0:
        recorder.probe["utilization_floor"] = min(area / space + 0.05, 1.0)
    result = original(engine, *args, **kwargs)
    recorder.probe["placement_completed"] = True
    metrics = getattr(engine, "metrics", None)
    overflows = metrics.get("overflow", []) if isinstance(metrics, dict) else []
    if overflows:
        recorder.ppa["overflow"] = _scalar_value(overflows[-1])
    return result


def _observe_cell_padding(recorder, original, placedb, params, *args, **kwargs):
    result = original(placedb, params, *args, **kwargs)
    padding = _scalar_value(getattr(placedb, "cell_padding_x", None))
    site = _scalar_value(getattr(placedb, "site_width", None))
    recorder.probe["cell_padding"] = {
        "padding_sites": padding / site
        if padding is not None and site is not None and site > 0
        else None,
        "geometry_apply_count": 1,
    }
    return result


def _observe_place_object_init(recorder, stack, original, model, *args, **kwargs):
    result = original(model, *args, **kwargs)
    recorder.model = model
    recorder.probe["place_object_count"] += 1
    _observe_native_model(model, recorder, stack)
    return result


def _observe_native_model(model, recorder, stack):
    operations = model.op_collections
    knob_id = recorder.patch["knob_id"]
    if knob_id == "place.target_density":
        for name in ("density_op", "fence_region_density_merged_op"):
            if callable(getattr(operations, name, None)):
                _patch_method(
                    stack, operations, name, partial(_observe_density_operator, recorder, model)
                )
    elif knob_id == "place.density_weight":
        _patch_method(
            stack,
            model,
            "initialize_density_weight",
            partial(_observe_density_weight_initialization, recorder),
        )
    elif knob_id == "place.routability_opt" and callable(
        getattr(operations, "adjust_node_area_op", None)
    ):
        _patch_method(
            stack, operations, "adjust_node_area_op", partial(_observe_routability_round, recorder)
        )


def _observe_density_operator(recorder, model, original, *args, **kwargs):
    result = original(*args, **kwargs)
    recorder.probe["density_operator_call_count"] += 1
    recorder.probe["target_density"] = _scalar_value(
        getattr(getattr(recorder.engine, "params", None), "target_density", None)
    )
    recorder.probe["density_tensor_value"] = _scalar_value(
        getattr(getattr(model, "data_collections", None), "target_density", None)
    )
    return result


def _observe_density_weight_initialization(recorder, original, *args, **kwargs):
    params = args[0] if args else kwargs.get("params")
    coefficient = _scalar_value(getattr(params, "density_weight", None))
    result = original(*args, **kwargs)
    recorder.probe["configured_density_weight"] = coefficient
    recorder.probe["initialization_count"] += 1
    return result


def _observe_routability_round(recorder, original, *args, **kwargs):
    result = original(*args, **kwargs)
    recorder.probe["routability_branch_round_count"] += 1
    return result


def _build_dreamplace_report(patch, engine, ppa, probe, *, engine_succeeded):
    knob_id = patch["knob_id"]
    params = getattr(engine, "params", None)
    ppa = ppa if isinstance(ppa, dict) else {}
    actual = None
    status = "unknown"
    reason = "Required runtime observation is unavailable."
    if knob_id == "place.target_density":
        observation = {
            key: probe.get(key)
            for key in (
                "target_density",
                "density_tensor_value",
                "utilization_floor",
            )
        }
        observation["density_operator_call_count"] = probe.get("density_operator_call_count", 0)
        value = observation["target_density"]
        if observation["density_operator_call_count"] > 0 and _same_number(
            value, observation["density_tensor_value"]
        ):
            actual, status, reason = value, "effective", None
    elif knob_id == "place.target_overflow":
        threshold = _scalar_value(getattr(params, "stop_overflow", None))
        final = _scalar_value(ppa.get("overflow"))
        # DREAMPlace uses -1 when no global-placement overflow was measured.
        if final is not None and final < 0:
            final = None
        observation = {"stop_overflow": threshold, "final_overflow": final}
        if threshold is not None and final is not None:
            if final < threshold:
                actual, status, reason = threshold, "effective", None
            else:
                status, reason = "inactive", "Final overflow did not fall below the threshold."
    elif knob_id == "place.cell_padding_x":
        padding = probe.get("cell_padding", {})
        observation = {
            "padding_sites": padding.get("padding_sites"),
            "geometry_apply_count": padding.get("geometry_apply_count", 0),
        }
        if observation["padding_sites"] is not None and observation["geometry_apply_count"] > 0:
            actual = observation["padding_sites"]
            if actual == 0 and patch["value"] > 0:
                status, reason = "inactive", "The requested positive padding was reduced to zero."
            else:
                status, reason = "effective", None
    elif knob_id == "place.density_weight":
        observation = {
            "configured_density_weight": probe.get("configured_density_weight"),
            "initialization_count": probe.get("initialization_count", 0),
        }
        if (
            observation["configured_density_weight"] is not None
            and observation["initialization_count"] > 0
        ):
            actual, status, reason = observation["configured_density_weight"], "effective", None
    else:
        configured = _scalar_value(getattr(params, "routability_opt_flag", None))
        configured = bool(configured) if configured in (0, 1) else None
        observation = {
            "configured_routability_opt": configured,
            "branch_round_count": probe.get("routability_branch_round_count", 0),
            "placement_completed": probe.get("placement_completed", False),
            "place_object_count": probe.get("place_object_count", 0),
        }
        if configured is True and patch["value"] is True and observation["branch_round_count"] > 0:
            actual, status, reason = True, "effective", None
        elif observation["placement_completed"] and observation["place_object_count"] > 0:
            if (
                configured is False
                and patch["value"] is False
                and observation["branch_round_count"] == 0
            ):
                actual, status, reason = False, "effective", None
            elif configured is not None:
                status, reason = "inactive", "The requested routability behavior did not occur."
    return {
        "schema_version": "tool.parameter_runtime_report.v2",
        "knob_id": knob_id,
        "written_value": patch["value"],
        "tool": {
            "name": "DREAMPlace",
            "revision": DREAMPLACE_OBSERVER_REVISION,
            "source_sha256": sha256_path(Path(__file__)),
        },
        "actual_value": actual,
        "status": status,
        "reason": reason,
        "observation": observation,
    }


def _scalar_value(value):
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        value = value.item()
    if type(value) in {bool, int}:
        return value
    return value if type(value) is float and math.isfinite(value) else None


def _same_number(left, right):
    return (
        type(left) in {int, float}
        and type(right) in {int, float}
        and math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
    )
