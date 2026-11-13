#!/usr/bin/env python
from collections.abc import Callable, Collection, Mapping
from functools import cache
from typing import Final

from chipcompiler.data import (
    DEFAULT_LEC_ENGINE,
    DEFAULT_SKIP_STEPS,
    INSERTABLE_FLOW_STEPS,
    LEC_STEP_TOOLS,
    LECEngineEnum,
    SkippableStepEnum,
    StateEnum,
    StepBaseEnum,
    StepEnum,
    ToolName,
    inserted_step_kind,
)
from chipcompiler.data.types import INSERTED_STEP_MARK

#: One built chain entry: (step, tool, state).
BuiltStep = tuple[StepBaseEnum | str, str, StateEnum | str]

#: The canonical rtl2gds chain as (step, tool); ``None`` takes the LEC engine.
#: Skip policies validate against this data, never a (patched) builder call.
_RTL2GDS_CHAIN: Final[tuple[tuple[StepBaseEnum, str | None], ...]] = (
    (StepEnum.SYNTHESIS, ToolName.YOSYS.value),
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
    the code default; a declared value validates through
    :meth:`LECEngineEnum.from_value`.
    """
    if not isinstance(flow_config, Mapping) or "lec_engine" not in flow_config:
        return DEFAULT_LEC_ENGINE
    return LECEngineEnum.from_value(flow_config["lec_engine"])


def resolve_skip_steps(flow_config: Mapping[str, object] | None) -> tuple[str, ...]:
    """The effective skip policy carried by a flow config.

    Presence-keyed: an absent ``skip_steps`` key yields the code default;
    an explicitly empty list yields ``()`` (run every step). Entries accept
    the same aliases as step ranges, must name steps of the rtl2gds chain,
    and normalize to canonical step values in canonical chain order
    (idempotently). ``lec`` is accepted and dropped: it was a chain step, and
    existing ecc.toml, project.json and params.toml files still list it;
    an LEC is inserted with ``insert_steps`` instead. Whether the remaining
    steps can run is decided by their capabilities
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
    requested.discard(StepEnum.LEC.value)
    chain_names = rtl2gds_step_names()
    unknown = sorted(requested - set(chain_names))
    if unknown:
        raise ValueError(
            f"skip_steps names unknown flow steps: {', '.join(unknown)}; "
            f"flow steps: {', '.join(chain_names)}"
        )
    return tuple(name for name in chain_names if name in requested)


def lec_insert_anchors() -> tuple[str, ...]:
    """The steps an LEC can be inserted after (``[flow] insert_steps``), in chain order.

    The design-building steps from Synthesis up to filler, each of which
    writes a netlist an LEC can check: ``lec@Synthesis`` compares the RTL with
    the mapped netlist (kepler-formal SEC), a later one compares the step's
    netlist with the synthesis netlist. filler has ``postRouteLec``.
    """
    names = rtl2gds_step_names()
    first = names.index(StepEnum.SYNTHESIS.value)
    last = names.index(StepEnum.FILLER.value)
    return tuple(step.value for step, tool in _RTL2GDS_CHAIN[first:last] if tool is not None)


def inserted_step_name(step: str, after: str) -> str:
    """The ledger name of *step* inserted after *after*: ``lec@CTS``.

    Spaces in *after* become underscores (``lec@Timing_optimization``), so the
    name is one shell word and a plain file name.
    """
    return f"{step}{INSERTED_STEP_MARK}{'_'.join(after.split())}"


def parse_inserted_step(name: str) -> tuple[str, str] | None:
    """(step, the step it follows) of a canonical inserted step name, else None."""
    return _canonical_inserted_steps().get(name)


@cache
def _canonical_inserted_steps() -> dict[str, tuple[str, str]]:
    """Every canonical inserted step name, with (step, the step it follows)."""
    return {
        inserted_step_name(kind, anchor): (kind, anchor)
        for kind in sorted(INSERTABLE_FLOW_STEPS)
        for anchor in lec_insert_anchors()
    }


def resolve_insert_steps(flow_config: Mapping[str, object] | None) -> tuple[str, ...]:
    """The inserted steps a flow config declares (``[flow] insert_steps``).

    Nothing is inserted when the key is absent. Entries are ``STEP@AFTER``;
    both names accept the selector aliases (``lec@timing_opt``). Only an
    insertable step (LEC) can be inserted, after a step of
    :func:`lec_insert_anchors`, at most once per step. Returns canonical
    names ordered by the step they follow; raises ``ValueError`` otherwise.
    """
    if not isinstance(flow_config, Mapping) or "insert_steps" not in flow_config:
        return ()
    raw = flow_config["insert_steps"]
    if not isinstance(raw, list):
        raise ValueError(f"insert_steps must be a list, not {type(raw).__name__}: {raw!r}")
    anchors = lec_insert_anchors()
    requested: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(f"insert_steps entries must be strings, not {entry!r}")
        step, mark, after = entry.partition(INSERTED_STEP_MARK)
        if not mark or not step.strip() or not after.strip():
            raise ValueError(
                f"insert_steps entry {entry!r} must be STEP{INSERTED_STEP_MARK}AFTER, "
                f"for example lec{INSERTED_STEP_MARK}CTS"
            )
        if normalize_flow_step(step) not in INSERTABLE_FLOW_STEPS:
            raise ValueError(
                f"insert_steps entry {entry!r}: only "
                f"{', '.join(sorted(INSERTABLE_FLOW_STEPS))} can be inserted"
            )
        anchor = normalize_flow_step(after)
        if anchor not in anchors:
            raise ValueError(
                f"insert_steps entry {entry!r}: lec can be inserted after {', '.join(anchors)}"
            )
        requested.add(anchor)
    return tuple(
        inserted_step_name(StepEnum.LEC.value, anchor) for anchor in anchors if anchor in requested
    )


def insert_flow_steps(
    steps: list, insert: Collection[str], lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE
) -> list:
    """*steps* with each inserted step right after the step it follows.

    An inserted step runs exactly when the step it follows runs: one whose
    step is not in *steps* (skipped, or outside a range) is left out, and so
    is one *steps* already holds (``synthesis_lec`` builds ``lec@Synthesis``).
    Inserted LEC steps use *lec_engine*.
    """
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    following: dict[str, str] = {}
    for name in insert:
        parsed = parse_inserted_step(name)
        if parsed is None:
            raise ValueError(f"not an inserted step: {name!r}")
        following[parsed[1]] = name
    names = [
        entry[0].value if isinstance(entry[0], StepBaseEnum) else str(entry[0]) for entry in steps
    ]
    result = []
    for name, entry in zip(names, steps, strict=True):
        result.append(entry)
        if name in following and following[name] not in names:
            result.append((following[name], lec_tool, StateEnum.Unstart))
    return result


def filter_flow_steps(steps: list, skip: Collection[str]) -> list:
    """Drop the skipped step entries from a built step list, order untouched.

    An inserted entry a chain builds itself (``synthesis_lec``) goes with the
    step it follows.
    """
    excluded = set(skip)

    def kept(entry) -> bool:
        name = entry[0].value if isinstance(entry[0], StepBaseEnum) else str(entry[0])
        parsed = parse_inserted_step(name)
        return name not in excluded and (parsed is None or parsed[1] not in excluded)

    return [entry for entry in steps if kept(entry)]


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

    def is_lec(step: StepBaseEnum | str) -> bool:
        name = step.value if isinstance(step, StepBaseEnum) else str(step)
        return (
            name == SkippableStepEnum.POST_ROUTE_LEC.value
            or inserted_step_kind(name) == StepEnum.LEC.value
        )

    return [
        (step, lec_tool if is_lec(step) and tool in LEC_STEP_TOOLS else tool, state)
        for step, tool, state in steps
    ]


def build_rtl2gds_flow(
    *,
    skip: Collection[str] = (),
    lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE,
    insert: Collection[str] = (),
) -> list:
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    steps = [
        (step, lec_tool if tool is None else tool, StateEnum.Unstart)
        for step, tool in _RTL2GDS_CHAIN
    ]
    return insert_flow_steps(filter_flow_steps(steps, skip), insert, lec_engine)


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
        "lec": StepEnum.LEC.value,
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
    insert: Collection[str] = (),
) -> list:
    """Return the inclusive canonical RTL-to-GDS range requested by a workspace.

    The RTL-to-GDS chain is owned by :func:`build_rtl2gds_flow`; partial flows
    are always slices of that chain rather than a second hand-maintained list.
    Skipped steps are excluded from the chain first, so a skipped step cannot
    serve as a range boundary (it is unknown in the filtered chain). Inserted
    steps follow their step inside the range, the range's last step included.
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
    return insert_flow_steps(steps[start_index : end_index + 1], insert, lec_engine)


def build_syn_sta_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, ToolName.YOSYS.value, StateEnum.Unstart))

    return steps


def build_synthesis_lec_flow(*, lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE) -> list:
    lec_tool = LECEngineEnum.from_value(lec_engine).value
    steps = []

    steps.append((StepEnum.SYNTHESIS, ToolName.YOSYS.value, StateEnum.Unstart))
    steps.append(
        (
            inserted_step_name(StepEnum.LEC.value, StepEnum.SYNTHESIS.value),
            lec_tool,
            StateEnum.Unstart,
        )
    )

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
