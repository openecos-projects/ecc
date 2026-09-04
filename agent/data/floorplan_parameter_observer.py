"""Agent-owned floorplan boundary and realized-geometry observation."""

import json
import math
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from functools import partial, wraps
from pathlib import Path
from threading import RLock, get_ident
from typing import Any

from .candidate_artifacts import canonical_json_bytes, sha256_bytes, sha256_path

FLOORPLAN_OBSERVER_REVISION = "ecc.agent.floorplan_parameter_observer.v1"
FLOORPLAN_KNOBS = frozenset({"floorplan.core_util", "floorplan.aspect_ratio"})
RUNTIME_REPORT_REF = "analysis/parameter_runtime_report.v1.json"
_MISSING = object()

# ponytail: serialize same-process observers; use permanent thread-local hooks
# if parallel flow throughput matters.
_OBSERVATION_LOCK = RLock()


@contextmanager
def capture_floorplan(patch: dict[str, Any]) -> Iterator[dict[str, Any]]:
    from chipcompiler.tools.ecc.module import ECCToolsModule

    boundary = {
        "init_fp_call_count": 0,
        "run_fp_call_count": 0,
    }
    with _OBSERVATION_LOCK, ExitStack() as stack:
        _patch_method(
            stack,
            ECCToolsModule,
            "init_fp",
            partial(_observe_floorplan_init, boundary),
        )
        _patch_method(
            stack,
            ECCToolsModule,
            "run_fp",
            partial(_observe_floorplan_run, boundary),
        )
        yield boundary


def _patch_method(stack, owner, name, observer) -> None:
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


def _restore_attribute(owner, name, previous) -> None:
    if previous is _MISSING:
        delattr(owner, name)
    else:
        setattr(owner, name, previous)


def _observe_floorplan_init(boundary, original, module, *args, **kwargs):
    config = kwargs.get("config", args[0] if args else None)
    boundary["init_fp_call_count"] += 1
    boundary["config_path"] = str(config) if config else None
    return original(module, *args, **kwargs)


def _observe_floorplan_run(boundary, original, module, *args, **kwargs):
    boundary["run_fp_call_count"] += 1
    return original(module, *args, **kwargs)


def build_floorplan_report(
    patch: dict[str, Any],
    boundary: dict[str, Any],
    feature_path: str | Path | None,
    *,
    engine_succeeded: bool,
) -> dict[str, Any]:
    knob_id = patch["knob_id"]
    config_path = Path(boundary["config_path"]) if boundary.get("config_path") else None
    config = _read_json(config_path)
    die_builder = config.get("die_builder", {}) if config else {}
    die_util = die_builder.get("die_util", {}) if isinstance(die_builder, dict) else {}
    field_name, consumer_id = {
        "floorplan.core_util": ("utilization", "ifp.die_builder.die_utilization"),
        "floorplan.aspect_ratio": (
            "aspect_ratio",
            "ifp.die_builder.die_aspect_ratio",
        ),
    }[knob_id]
    configured = _scalar_value(die_util.get(field_name))
    geometry = _floorplan_geometry(feature_path)
    realized = geometry.get(
        "core_utilization" if knob_id == "floorplan.core_util" else "aspect_ratio"
    )
    boundary_complete = (
        boundary.get("init_fp_call_count") == 1
        and boundary.get("run_fp_call_count") == 1
        and configured == patch["value"]
    )
    mode_active = die_builder.get("mode") == "die_util"
    used = engine_succeeded and boundary_complete and mode_active and realized is not None
    not_activated = engine_succeeded and boundary_complete and not mode_active
    status = "used" if used else "not_activated" if not_activated else "unknown"
    observation = _floorplan_observation(
        configured,
        realized,
        geometry,
        boundary,
        config_path,
        die_builder.get("mode"),
        mode_active=mode_active,
        realized_available=used,
        evidence_complete=used or not_activated,
    )
    outcome = "geometry_constructed" if used else "evaluated"
    evidence = _consumer_evidence(consumer_id, outcome, observation)
    return {
        "knob_id": knob_id,
        "requested_value": patch["value"],
        "tool": {
            "name": "ECC-Floorplan",
            "revision": FLOORPLAN_OBSERVER_REVISION,
            "source_sha256": sha256_path(Path(__file__)),
        },
        "application_status": ("applied" if engine_succeeded and boundary_complete else "unknown"),
        "effective_initial": {"value": configured, "unit": "ratio"},
        "effective_final": {"value": realized if used else None, "unit": "ratio"},
        "activation": {
            "status": status,
            "consumers": [evidence] if status in {"used", "not_activated"} else [],
        },
        "transitions": _floorplan_transitions(configured, realized, evidence) if used else [],
        "consumer_observation": observation,
    }


def _floorplan_observation(
    configured,
    realized,
    geometry,
    boundary,
    config_path,
    mode,
    *,
    mode_active,
    realized_available,
    evidence_complete,
) -> dict[str, Any]:
    lifecycle = [("adopted", configured, "ratio", "agent_python_boundary")]
    if mode_active:
        lifecycle.append(("consumed", configured, "ratio", "native_call_boundary"))
    if realized_available:
        lifecycle.append(("realized", realized, "ratio", "derived_verified_artifact"))
    return {
        "evidence_kind": "boundary_and_derived_output",
        "configured_value": configured,
        "mode": mode,
        "init_fp_call_count": boundary.get("init_fp_call_count", 0),
        "run_fp_call_count": boundary.get("run_fp_call_count", 0),
        "config_sha256": sha256_path(config_path) if config_path else None,
        "core_geometry": geometry.get("core_geometry"),
        "realized_core_utilization": geometry.get("core_utilization"),
        "realized_aspect_ratio": geometry.get("aspect_ratio"),
        "evidence_complete": evidence_complete,
        "lifecycle": _lifecycle(*lifecycle),
    }


def _consumer_evidence(consumer_id, outcome, observation) -> dict[str, Any]:
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


def _floorplan_transitions(configured, realized, evidence) -> list[dict[str, Any]]:
    if configured == realized:
        return []
    return [
        {
            "sequence": 0,
            "from": "adopted",
            "to": "adjusted",
            "value": realized,
            "reason": "Floorplan geometry realization",
            "evidence_ref": RUNTIME_REPORT_REF,
            "evidence_sha256": evidence["evidence_sha256"],
        }
    ]


def _floorplan_geometry(feature_path: str | Path | None) -> dict[str, Any]:
    feature = _read_json(Path(feature_path)) if feature_path else None
    layout = feature.get("Design Layout", {}) if feature else {}
    width = _scalar_value(layout.get("core_bounding_width"))
    height = _scalar_value(layout.get("core_bounding_height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return {}
    ratio = width / height
    return {
        "core_utilization": _scalar_value(layout.get("core_usage")),
        "aspect_ratio": ratio,
        "core_geometry": {
            "width": {"value": width, "unit": "um"},
            "height": {"value": height, "unit": "um"},
            "area": {
                "value": _scalar_value(layout.get("core_area")),
                "unit": "um^2",
            },
            "aspect_ratio": {"value": ratio, "unit": "ratio"},
        },
    }


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def step_path(step: Any, group: str, name: str) -> str | Path | None:
    value = getattr(step, group, None)
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _scalar_value(value: Any):
    if type(value) is int:
        return value
    return value if type(value) is float and math.isfinite(value) else None


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
