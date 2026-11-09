#!/usr/bin/env python
from collections.abc import Callable, Collection, Mapping
from typing import Final

from chipcompiler.data import (
    DEFAULT_LEC_ENGINE,
    DEFAULT_SKIP_STEPS,
    LEC_STEP_TOOLS,
    LECEngineEnum,
    SkippableStepEnum,
    StateEnum,
    StepBaseEnum,
    StepEnum,
    ToolName,
)

#: One built chain entry: (step, tool, state).
BuiltStep = tuple[StepBaseEnum | str, str, StateEnum | str]

#: The canonical rtl2gds chain as (step, tool); ``None`` takes the LEC engine.
#: Skip policies validate against this data, never a (patched) builder call.
_RTL2GDS_CHAIN: Final[tuple[tuple[StepBaseEnum, str | None], ...]] = (
    (StepEnum.SYNTHESIS, ToolName.YOSYS.value),
    (SkippableStepEnum.LEC, None),
    (StepEnum.PRE_FLOORPLAN, ToolName.ECC.value),
    (StepEnum.MACRO_PLACEMENT, ToolName.DREAMPLACE.value),
    (StepEnum.POST_FLOORPLAN, ToolName.ECC.value),
    (StepEnum.PREPLACE, ToolName.SIZER.value),
    (StepEnum.PLACEMENT, ToolName.DREAMPLACE.value),
    (SkippableStepEnum.DIFF_OPT, ToolName.DREAMPLACE.value),
    (StepEnum.DIFF_SIZING, ToolName.DREAMPLACE.value),
    (StepEnum.CTS, ToolName.ECC.value),
    (StepEnum.LEGALIZATION, ToolName.DREAMPLACE.value),
    (SkippableStepEnum.TIMING_OPT, ToolName.SIZER.value),
    (StepEnum.ROUTING, ToolName.ECC.value),
    (StepEnum.FILLER, ToolName.ECC.value),
    (StepEnum.LVS, ToolName.ECC.value),
    (StepEnum.DRC, ToolName.ECC.value),
    (StepEnum.ANTENNA_CHECK, ToolName.ECC.value),
    (SkippableStepEnum.POST_ROUTE_LEC, None),
    (StepEnum.RCX, ToolName.ECC.value),
    (StepEnum.STA, ToolName.ECC.value),
    (StepEnum.POWER_ANALYSIS, ToolName.ECC.value),
    (StepEnum.EMIR, ToolName.ECC.value),
    (StepEnum.HARDEN, ToolName.ECC.value),
)


def rtl2gds_step_names() -> tuple[str, ...]:
    """The canonical rtl2gds step names, in chain order."""
    return tuple(step.value for step, _tool in _RTL2GDS_CHAIN)


def resolve_lec_engine(flow_config: Mapping[str, object] | None) -> LECEngineEnum:
    """The LEC engine a flow config declares.

    Presence-keyed like the skip policy: an absent ``lec_engine`` key yields
    the code default; a declared value validates and normalizes through
    :meth:`LECEngineEnum.from_value` (the ``dual`` alias becomes ``lec_dual``).
    """
    if not isinstance(flow_config, Mapping) or "lec_engine" not in flow_config:
        return DEFAULT_LEC_ENGINE
    return LECEngineEnum.from_value(flow_config["lec_engine"])


def resolve_skip_steps(flow_config: Mapping[str, object] | None) -> tuple[str, ...]:
    """The effective skip policy carried by a flow config.

    Presence-keyed: an absent ``skip_steps`` key yields the code default;
    an explicitly empty list yields ``()`` (run every step). To enable
    ``diff_opt`` alone, declare ``["lec"]``. Entries accept the same aliases as step
    ranges, must name steps of the rtl2gds chain, and normalize to canonical
    step values in canonical chain order (idempotently). Whether the
    remaining steps can run is decided by their capabilities
    (:func:`chipcompiler.data.flow_plan.plan_flow`), not here.
    """
    if not isinstance(flow_config, Mapping) or "skip_steps" not in flow_config:
        return DEFAULT_SKIP_STEPS
    raw = flow_config["skip_steps"]
    if not isinstance(raw, list):
        raise ValueError(f"skip_steps must be a list, not {type(raw).__name__}: {raw!r}")
    requested = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(f"skip_steps entries must be strings, not {entry!r}")
        requested.add(normalize_flow_step(entry))
    chain_names = rtl2gds_step_names()
    unknown = sorted(requested - set(chain_names))
    if unknown:
        raise ValueError(
            f"skip_steps names unknown flow steps: {', '.join(unknown)}; "
            f"flow steps: {', '.join(chain_names)}"
        )
    return tuple(name for name in chain_names if name in requested)


def filter_flow_steps(steps: list, skip: Collection[str]) -> list:
    """Drop the skipped step entries from a built step list, order untouched."""
    excluded = set(skip)
    return [
        entry
        for entry in steps
        if (entry[0].value if isinstance(entry[0], StepBaseEnum) else str(entry[0])) not in excluded
    ]


def substitute_lec_engine(
    steps: list[BuiltStep], lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE
) -> list[BuiltStep]:
    """Replace the tool of a built chain's LEC entries with the engine.

    For callers that build a preset chain through the no-arg discovery
    table (CLI run creation, preflight) and apply the configured engine
    afterwards — the same rule the canonical builders apply at
    construction time.
    """
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    lec_names = {SkippableStepEnum.LEC.value, SkippableStepEnum.POST_ROUTE_LEC.value}
    return [
        (
            step,
            lec_tool
            if (step.value if isinstance(step, StepBaseEnum) else str(step)) in lec_names
            and tool in LEC_STEP_TOOLS
            else tool,
            state,
        )
        for step, tool, state in steps
    ]


def build_rtl2gds_flow(
    *, skip: Collection[str] = (), lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE
) -> list:
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    steps = [
        (step, lec_tool if tool is None else tool, StateEnum.Unstart)
        for step, tool in _RTL2GDS_CHAIN
    ]
    return filter_flow_steps(steps, skip)


def normalize_flow_step(value: str | StepBaseEnum) -> str:
    """Resolve a CLI/manifest step spelling to its canonical flow name."""
    if isinstance(value, StepBaseEnum):
        return value.value
    token = str(value or "").strip()
    if not token:
        return ""
    alias_key = token.lower().replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "synth": StepEnum.SYNTHESIS.value,
        "synthesis": StepEnum.SYNTHESIS.value,
        "prefloorplan": StepEnum.PRE_FLOORPLAN.value,
        "floorplan": StepEnum.PRE_FLOORPLAN.value,
        "macro": StepEnum.MACRO_PLACEMENT.value,
        "macroplace": StepEnum.MACRO_PLACEMENT.value,
        "macroplacement": StepEnum.MACRO_PLACEMENT.value,
        "postfloorplan": StepEnum.POST_FLOORPLAN.value,
        "preplace": StepEnum.PREPLACE.value,
        "preplaceopt": StepEnum.PREPLACE.value,
        "preplaceoptimization": StepEnum.PREPLACE.value,
        "place": StepEnum.PLACEMENT.value,
        "placement": StepEnum.PLACEMENT.value,
        "diffopt": SkippableStepEnum.DIFF_OPT.value,
        "diffoptimization": SkippableStepEnum.DIFF_OPT.value,
        "diffsizing": StepEnum.DIFF_SIZING.value,
        "cts": StepEnum.CTS.value,
        "legal": StepEnum.LEGALIZATION.value,
        "legalization": StepEnum.LEGALIZATION.value,
        "timingopt": SkippableStepEnum.TIMING_OPT.value,
        "timingoptimization": SkippableStepEnum.TIMING_OPT.value,
        "route": StepEnum.ROUTING.value,
        "routing": StepEnum.ROUTING.value,
        "drc": StepEnum.DRC.value,
        "antenna": StepEnum.ANTENNA_CHECK.value,
        "antennacheck": StepEnum.ANTENNA_CHECK.value,
        "lvs": StepEnum.LVS.value,
        "filler": StepEnum.FILLER.value,
        "lec": SkippableStepEnum.LEC.value,
        "postlec": SkippableStepEnum.POST_ROUTE_LEC.value,
        "postroutelec": SkippableStepEnum.POST_ROUTE_LEC.value,
        "rcx": StepEnum.RCX.value,
        "sta": StepEnum.STA.value,
        "poweranalysis": StepEnum.POWER_ANALYSIS.value,
        "emir": StepEnum.EMIR.value,
        "harden": StepEnum.HARDEN.value,
        "defview": StepEnum.DEFVIEW.value,
    }
    return aliases.get(alias_key, token)


def build_flow_range(
    from_step: str | StepBaseEnum,
    to_step: str | StepBaseEnum,
    *,
    skip: Collection[str] = (),
    lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE,
) -> list:
    """Return the inclusive canonical RTL-to-GDS range requested by a workspace.

    The RTL-to-GDS chain is owned by :func:`build_rtl2gds_flow`; partial flows
    are always slices of that chain rather than a second hand-maintained list.
    Skipped steps are excluded from the chain first, so a skipped step cannot
    serve as a range boundary (it is unknown in the filtered chain).
    """
    steps = build_rtl2gds_flow(skip=skip, lec_engine=lec_engine)
    names = [
        step.value if isinstance(step, StepBaseEnum) else str(step) for step, _tool, _state in steps
    ]
    first = normalize_flow_step(from_step)
    last = normalize_flow_step(to_step)
    if first not in names or last not in names:
        available = ", ".join(names)
        raise ValueError(
            f"unknown flow step: {from_step!r} -> {to_step!r}; available steps: {available}"
        )
    start_index = names.index(first)
    end_index = names.index(last)
    if start_index > end_index:
        raise ValueError(f"flow range is reversed: {from_step!r} -> {to_step!r}")
    return steps[start_index : end_index + 1]


def build_syn_sta_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, ToolName.YOSYS.value, StateEnum.Unstart))

    return steps


def build_synthesis_lec_flow(*, lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE) -> list:
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    steps = []

    steps.append((StepEnum.SYNTHESIS, ToolName.YOSYS.value, StateEnum.Unstart))
    steps.append((SkippableStepEnum.LEC, lec_tool, StateEnum.Unstart))

    return steps


def build_defview_flow() -> list:
    """LEF+DEF layout preview: load the design DEF and export a geometry snapshot."""
    return [(StepEnum.DEFVIEW, ToolName.ECC.value, StateEnum.Unstart)]


def get_flow_builders() -> dict[str, Callable[[], list[BuiltStep]]]:
    """Discover flow presets from the build_*_flow defs in this module."""
    builders = {}
    for name, fn in globals().items():
        if not (callable(fn) and name.startswith("build_") and name.endswith("_flow")):
            continue
        preset = name[len("build_") : -len("_flow")]
        if preset:
            builders[preset] = fn
    return builders
