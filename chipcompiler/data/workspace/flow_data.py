"""Flow-config to ledger construction for workspaces.

Turns a creation ``flow_config`` (preset, range, or explicit step
selection, plus an optional declared skip policy) into the initial
``flow.json`` ledger data and the canonical chain entries every consumer
(reconcile, config validation) slices from. Pure computation: no IO.
"""

from chipcompiler.data.types import StateEnum, StepBaseEnum


def _canonical_rtl2gds_flow_entries() -> list[tuple[str, str, str]]:
    import chipcompiler.rtl2gds as rtl2gds_api

    return [
        (
            step.value if isinstance(step, StepBaseEnum) else str(step),
            str(tool),
            state.value if isinstance(state, StateEnum) else str(state),
        )
        for step, tool, state in rtl2gds_api.build_rtl2gds_flow()
    ]


def build_dynamic_flow_data(flow_config: dict | None) -> dict:
    """Build initial flow.json data from GUI-provided flow_config.

    A non-contiguous explicit selection degrades to the contiguous
    first..last range (with a log note) so flow.json and the [flow] target
    always describe the same steps. A preset-shaped config selects the
    preset's canonical range. The config's skip policy is resolved here:
    skipped steps never enter the ledger.
    """
    if not isinstance(flow_config, dict) or not flow_config:
        return {}

    from ..workspace_config import flow_range_for_preset, resolve_flow_selection

    if "preset" in flow_config and "start_step" not in flow_config and "steps" not in flow_config:
        first, last = flow_range_for_preset(flow_config["preset"])
        selected_names = [first, last]
    else:
        selected_names, _degraded = resolve_flow_selection(
            flow_config, _canonical_rtl2gds_flow_entries()
        )
    if not selected_names:
        return {}

    import chipcompiler.rtl2gds as rtl2gds_api

    skip = rtl2gds_api.resolve_skip_steps(flow_config)
    selected = rtl2gds_api.build_flow_range(selected_names[0], selected_names[-1], skip=skip)
    return {
        "steps": [
            _flow_step_template(
                name.value if isinstance(name, StepBaseEnum) else str(name),
                str(tool),
                state.value if isinstance(state, StateEnum) else str(state),
            )
            for name, tool, state in selected
        ]
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


def _flow_step_template(name: str, tool: str, state: str) -> dict:
    return {
        "name": name,
        "tool": tool,
        "state": state,
        "runtime": "",
        "peak memory (mb)": 0,
        "info": {},
    }
