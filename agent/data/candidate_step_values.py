"""Candidate DreamPlace values held per flow step in the parameter store.

Each DreamPlace step resolves ``<step dir>/config/dreamplace_ecc.json`` from the
workspace baseline plus that step's values in ``step_params`` (``params.toml``),
so a candidate seed or DreamPlace knob is stored as a step value: writing the
shared baseline would be overridden by stored step values, or leak to every
DreamPlace step.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from chipcompiler.data.config_params.common import ParamSchema
from chipcompiler.data.parameter_schema import list_schemas, lookup_schema
from chipcompiler.data.step_parameters import STEP_SCOPED_CONFIG, step_value

from .candidate_registry import CandidateKnob, candidate_knob_registry

SEED_PARAMETER = "place.random_seed"
#: Receipt config key of the parameter store (``home/params.toml``).
PARAMETER_STORE_KEY = "parameters"
_MISSING = object()


class CandidateStepValueError(ValueError):
    """A candidate step value is missing from the store or the executed step config."""


def is_step_value_knob(knob: CandidateKnob) -> bool:
    """Whether *knob* is a DreamPlace knob, stored as a value of its target step."""
    return knob.config_key == STEP_SCOPED_CONFIG


def knob_store_key(knob: CandidateKnob) -> str:
    """The config a knob's materialization writes (and its receipt snapshots)."""
    return PARAMETER_STORE_KEY if is_step_value_knob(knob) else knob.config_key


def knob_step_parameter(knob: CandidateKnob) -> ParamSchema:
    """The step-scoped parameter of the knob's target step that sets its DreamPlace key.

    Several parameters may set one DreamPlace field on different steps
    (``place.cell_padding_x`` on placement, ``legalization.cell_padding_x``
    on legalization); the one declared for the target step is the knob's.
    """
    for schema in list_schemas():
        target = schema.config_target
        if (
            target is not None
            and target.config_key == knob.config_key
            and target.json_path == knob.json_path
            and schema.applies_to(knob.target_step)
        ):
            return schema
    raise CandidateStepValueError(
        f"knob {knob.knob_id} has no {knob.target_step} parameter for {'.'.join(knob.json_path)}"
    )


def knob_store_value(knob: CandidateKnob, value: Any) -> Any:
    return int(value) if knob.value_type == "bool_int" else value


def seed_steps(steps: Iterable[Any]) -> list[str]:
    """Names of the DreamPlace *steps* that consume the DreamPlace random seed."""
    schema = _seed_schema()
    return [
        name
        for step in steps
        if (name := _step_name(step))
        and _step_tool(step) == "dreamplace"
        and schema.applies_to(name)
    ]


def store_candidate_seed(workspace: Any, step_names: list[str], seed: int) -> None:
    """Store *seed* as the seed value of each of *step_names* and persist ``params.toml``."""
    if not step_names:
        return
    from chipcompiler.data.parameter import save_parameter
    from chipcompiler.data.workspace_parameters import update_workspace_param_value

    schema = _seed_schema()
    for name in step_names:
        update_workspace_param_value(workspace, schema, seed, step=name)
    if not save_parameter(workspace.parameters):
        raise CandidateStepValueError("candidate seed could not be saved")


def verify_candidate_seed_store(workspace: Any, step_names: list[str], seed: int) -> None:
    data = getattr(getattr(workspace, "parameters", None), "data", None) or {}
    for name in step_names:
        if step_value(data, name, SEED_PARAMETER, _MISSING) != seed:
            raise CandidateStepValueError(f"candidate seed is not stored for step {name}")


def expected_step_config_values(
    written_patch: list[dict[str, Any]], seed_step_names: list[str], seed: int
) -> dict[str, dict[tuple[str, ...], Any]]:
    """``{step: {json path: value}}`` each executed DreamPlace step file must hold.

    *written_patch* is the materialized patch (``candidate_written_patch``).
    """
    expected: dict[str, dict[tuple[str, ...], Any]] = {
        name: {("random_seed",): seed} for name in seed_step_names
    }
    registry = {knob.knob_id: knob for knob in candidate_knob_registry()}
    for item in written_patch:
        knob = registry.get(item["knob_id"])
        if knob is not None and is_step_value_knob(knob):
            expected.setdefault(knob.target_step, {})[knob.json_path] = knob_store_value(
                knob, item["value"]
            )
    return expected


def verify_executed_step_configs(
    executed_steps: Iterable[Any], expected: dict[str, dict[tuple[str, ...], Any]]
) -> None:
    """Check each executed step's own DreamPlace config holds its candidate values."""
    for step in executed_steps:
        name = _step_name(step)
        if name not in expected:
            continue
        path = _step_config_path(step)
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CandidateStepValueError(f"candidate step config is unreadable: {name}") from exc
        actual = {key: _nested(config, key) for key in expected[name]}
        if actual != expected[name]:
            raise CandidateStepValueError(
                f"candidate step config does not hold the candidate values: {name}"
            )


def _step_config_path(step: Any) -> Path:
    from chipcompiler.tools.ecc_dreamplace.builder import STEP_CONFIG_FILE

    directory = getattr(step, "directory", None)
    if not directory:
        raise CandidateStepValueError(f"candidate step has no directory: {_step_name(step)}")
    return Path(directory) / "config" / STEP_CONFIG_FILE


def _nested(config: object, path: tuple[str, ...]) -> object:
    for key in path:
        if not isinstance(config, dict) or key not in config:
            return None
        config = config[key]
    return config


def _step_name(step: Any) -> str | None:
    name = step.get("name") if isinstance(step, dict) else getattr(step, "name", None)
    return name if isinstance(name, str) else None


def _step_tool(step: Any) -> str | None:
    return step.get("tool") if isinstance(step, dict) else getattr(step, "tool", None)


def _seed_schema() -> ParamSchema:
    schema = lookup_schema(SEED_PARAMETER)
    if schema is None:
        raise CandidateStepValueError(f"unknown parameter: {SEED_PARAMETER}")
    return schema
