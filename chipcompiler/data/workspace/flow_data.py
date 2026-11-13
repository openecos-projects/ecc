"""Flow-config to ledger construction for workspaces.

Turns a creation ``flow_config`` (preset, range, or explicit step
selection, plus an optional declared skip policy) into the initial
``flow.json`` ledger data and the canonical chain entries every consumer
(reconcile, config validation) slices from. Pure computation: no IO.
"""

from chipcompiler.data.step import new_step_directory
from chipcompiler.data.types import (
    StateEnum,
    StepBaseEnum,
    default_flow_step_category,
)

from ..schema_versions import FLOW_JSON, SCHEMA_VERSION_FIELD, SUPPORTED_SCHEMA_VERSIONS
from .flow_types import FlowDocument, FlowStepEntry

#: The schema_version written into home/flow.json ledgers.
FLOW_JSON_SCHEMA_VERSION = SUPPORTED_SCHEMA_VERSIONS[FLOW_JSON]


def _entries_of(steps) -> list[tuple[str, str, str]]:
    return [
        (
            step.value if isinstance(step, StepBaseEnum) else str(step),
            str(tool),
            state.value if isinstance(state, StateEnum) else str(state),
        )
        for step, tool, state in steps
    ]


def _canonical_rtl2gds_flow_entries() -> list[tuple[str, str, str]]:
    import chipcompiler.rtl2gds as rtl2gds_api

    return _entries_of(rtl2gds_api.build_rtl2gds_flow())


def _flow_entries_for_config(flow_config: dict) -> list[tuple[str, str, str]]:
    """The chain a flow_config selects against.

    A declared non-canonical preset (for example ``defview``) slices its
    own builder's steps; every other config selects from the canonical
    rtl2gds chain.
    """
    import chipcompiler.rtl2gds as rtl2gds_api

    preset = flow_config.get("preset")
    if isinstance(preset, str) and preset != "rtl2gds":
        builder = rtl2gds_api.get_flow_builders().get(preset)
        if builder is not None:
            return _entries_of(builder())
    return _canonical_rtl2gds_flow_entries()


def build_dynamic_flow_data(flow_config: dict | None) -> FlowDocument:
    """Build initial flow.json data from GUI-provided flow_config.

    A non-contiguous explicit selection degrades to the contiguous
    first..last range (with a log note) so flow.json and the [flow] target
    always describe the same steps. A preset-shaped config selects the
    preset's chain, whose first step may be skipped. The config's skip
    policy and inserted steps are resolved here: skipped steps never enter
    the ledger, an inserted step follows the step it is inserted after, and
    a selection whose remaining steps lack required design data
    (:func:`~chipcompiler.data.flow_plan.plan_flow`) raises ``ValueError``.
    """
    if not isinstance(flow_config, dict) or not flow_config:
        return {}

    from ..workspace_config import flow_range_for_preset, resolve_flow_selection

    entries = _flow_entries_for_config(flow_config)
    start: str | None = None
    end: str | None = None
    if "preset" in flow_config and "start_step" not in flow_config and "steps" not in flow_config:
        # _flow_entries_for_config falls back to the canonical chain.
        flow_range_for_preset(flow_config["preset"])  # raises on unknown presets
    else:
        selected_names, _degraded = resolve_flow_selection(flow_config, entries)
        if not selected_names:
            return {}
        start, end = selected_names[0], selected_names[-1]

    import chipcompiler.rtl2gds as rtl2gds_api
    from chipcompiler.data.flow_plan import inserted_chain, plan_flow

    skip = rtl2gds_api.resolve_skip_steps(flow_config)
    lec_engine = rtl2gds_api.resolve_lec_engine(flow_config)
    plan = plan_flow(
        [(name, tool) for name, tool, _state in entries],
        skip_steps=skip,
        inserted=inserted_chain(
            rtl2gds_api.resolve_insert_steps(flow_config), lec_engine=lec_engine
        ),
        start=start,
        end=end,
    )
    if plan.errors:
        raise ValueError(
            "skip_steps leaves steps without required design data: "
            + "; ".join(violation.message() for violation in plan.errors)
        )
    selected = rtl2gds_api.substitute_lec_engine(
        [(step.name, step.tool, StateEnum.Unstart) for step in plan.steps if step.enabled],
        lec_engine,
    )
    return {
        SCHEMA_VERSION_FIELD: FLOW_JSON_SCHEMA_VERSION,
        "steps": [
            _flow_step_template(
                name.value if isinstance(name, StepBaseEnum) else str(name),
                str(tool),
                state.value if isinstance(state, StateEnum) else str(state),
                index=index,
            )
            for index, (name, tool, state) in enumerate(selected, start=1)
        ],
    }


def _selected_dynamic_flow_step_names(
    flow_config: dict,
    canonical_steps: list[tuple[str, str, str]],
) -> list[str]:
    canonical_names = [name for name, _tool, _state in canonical_steps]
    canonical_name_set = set(canonical_names)

    raw_steps = flow_config.get("steps", [])
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    if isinstance(raw_steps, (list, tuple)):
        requested = {
            name
            for name in (_normalize_flow_step_name(item) for item in raw_steps)
            if name in canonical_name_set
        }
        if requested:
            return [name for name in canonical_names if name in requested]

    start_step = _normalize_flow_step_name(flow_config.get("start_step"))
    end_step = _normalize_flow_step_name(flow_config.get("end_step"))
    if start_step not in canonical_name_set or end_step not in canonical_name_set:
        return []

    start_index = canonical_names.index(start_step)
    end_index = canonical_names.index(end_step)
    start = min(start_index, end_index)
    end = max(start_index, end_index)
    return canonical_names[start : end + 1]


def _normalize_flow_step_name(value) -> str:
    from chipcompiler.rtl2gds import normalize_flow_step

    return normalize_flow_step(value)


def _flow_step_template(name: str, tool: str, state: str, *, index: int | None) -> FlowStepEntry:
    return {
        "name": name,
        "tool": tool,
        "category": default_flow_step_category(name).value,
        "state": state,
        "directory": new_step_directory(name, tool, index=index),
        "runtime": "",
        "peak memory (mb)": 0,
        "info": {},
    }
