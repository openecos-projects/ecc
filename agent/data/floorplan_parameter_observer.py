"""Agent-owned observation of the two controlled floorplan parameters."""

import json
import math
from contextlib import ExitStack, contextmanager
from functools import partial
from pathlib import Path
from threading import RLock

from .candidate_artifacts import sha256_path
from .parameter_runtime_observer import _patch_method

FLOORPLAN_OBSERVER_REVISION = "ecc.agent.floorplan_parameter_observer.v2"
FLOORPLAN_KNOBS = frozenset({"floorplan.core_util", "floorplan.aspect_ratio"})
# ponytail: serialize same-process observers; use thread-local hooks if throughput matters.
_OBSERVATION_LOCK = RLock()


@contextmanager
def capture_floorplan(patch):
    from chipcompiler.tools.ecc.module import ECCToolsModule

    boundary = {"init_fp_call_count": 0, "run_fp_call_count": 0, "run_fp_completed": False}
    with _OBSERVATION_LOCK, ExitStack() as stack:
        _patch_method(stack, ECCToolsModule, "init_fp", partial(_observe_floorplan_init, boundary))
        _patch_method(stack, ECCToolsModule, "run_fp", partial(_observe_floorplan_run, boundary))
        yield boundary


def _observe_floorplan_init(boundary, original, module, *args, **kwargs):
    config = kwargs.get("config", args[0] if args else None)
    result = original(module, *args, **kwargs)
    boundary["init_fp_call_count"] += 1
    boundary["config_path"] = str(config) if config else None
    return result


def _observe_floorplan_run(boundary, original, module, *args, **kwargs):
    boundary["run_fp_call_count"] += 1
    result = original(module, *args, **kwargs)
    boundary["run_fp_completed"] = result is not False
    return result


def build_floorplan_report(patch, boundary, feature_path, *, engine_succeeded):
    knob_id = patch["knob_id"]
    config = _read_json(boundary.get("config_path"))
    die_builder = config.get("die_builder", {})
    die_util = die_builder.get("die_util", {})
    field = "utilization" if knob_id == "floorplan.core_util" else "aspect_ratio"
    configured = _scalar_value(die_util.get(field))
    feature = _read_json(feature_path).get("Design Layout", {})
    width = _scalar_value(feature.get("core_bounding_width"))
    height = _scalar_value(feature.get("core_bounding_height"))
    geometry = (
        boundary.get("run_fp_completed", False)
        and width is not None
        and width > 0
        and height is not None
        and height > 0
    )
    observation = {
        "mode": die_builder.get("mode"),
        "configured_value": configured,
        "init_fp_call_count": boundary.get("init_fp_call_count", 0),
        "run_fp_call_count": boundary.get("run_fp_call_count", 0),
        "geometry_constructed": geometry,
    }
    actual, status, reason = None, "unknown", "Required floorplan observation is unavailable."
    if (
        observation["init_fp_call_count"] == 1
        and observation["run_fp_call_count"] == 1
        and boundary.get("run_fp_completed", False)
    ):
        if observation["mode"] == "die_size":
            status, reason = "inactive", "Fixed die dimensions do not use this parameter."
        elif observation["mode"] == "die_util" and geometry and configured is not None:
            actual, status, reason = configured, "effective", None
    return {
        "schema_version": "tool.parameter_runtime_report.v2",
        "knob_id": knob_id,
        "written_value": patch["value"],
        "tool": {
            "name": "ECC-Floorplan",
            "revision": FLOORPLAN_OBSERVER_REVISION,
            "source_sha256": sha256_path(Path(__file__)),
        },
        "actual_value": actual,
        "status": status,
        "reason": reason,
        "observation": observation,
    }


def _read_json(path):
    if path is None:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def step_path(step, group, name):
    value = getattr(step, group, None)
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _scalar_value(value):
    if type(value) is int:
        return value
    return value if type(value) is float and math.isfinite(value) else None
