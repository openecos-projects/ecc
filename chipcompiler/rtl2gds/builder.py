#!/usr/bin/env python
from collections.abc import Callable, Collection

from chipcompiler.data import (
    DEFAULT_SKIP_STEPS,
    SkippableStepEnum,
    StateEnum,
    StepBaseEnum,
    StepEnum,
)

# Step values a project is allowed to exclude from its ledger.
SKIPPABLE_STEP_VALUES = frozenset(member.value for member in SkippableStepEnum)


def resolve_skip_steps(flow_config: dict | None) -> tuple[str, ...]:
    """The effective skip policy carried by a flow config.

    Presence-keyed: an absent ``skip_steps`` key yields the code default;
    an explicitly empty list yields ``()`` (run every step — the only way
    to enable the synthesis LEC). Entries accept the same aliases as step
    ranges, must name skippable steps only, and normalize to canonical
    step values in canonical chain order (idempotently).
    """
    if not isinstance(flow_config, dict) or "skip_steps" not in flow_config:
        return DEFAULT_SKIP_STEPS
    raw = flow_config["skip_steps"]
    if not isinstance(raw, list):
        raise ValueError(f"skip_steps must be a list, not {type(raw).__name__}: {raw!r}")
    requested = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(f"skip_steps entries must be strings, not {entry!r}")
        requested.add(normalize_flow_step(entry))
    illegal = sorted(requested - SKIPPABLE_STEP_VALUES)
    if illegal:
        legal = ", ".join(sorted(SKIPPABLE_STEP_VALUES))
        raise ValueError(
            f"skip_steps names steps that cannot be skipped: {', '.join(illegal)}; "
            f"skippable steps: {legal}"
        )
    chain_names = [
        step.value if isinstance(step, StepBaseEnum) else str(step)
        for step, _tool, _state in build_rtl2gds_flow()
    ]
    return tuple(name for name in chain_names if name in requested)


def filter_flow_steps(steps: list, skip: Collection[str]) -> list:
    """Drop the skipped step entries from a built step list, order untouched."""
    excluded = set(skip)
    return [
        entry
        for entry in steps
        if (entry[0].value if isinstance(entry[0], StepBaseEnum) else str(entry[0])) not in excluded
    ]


def build_rtl2gds_flow(*, skip: Collection[str] = ()) -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    steps.append((SkippableStepEnum.LEC, "yosys_lec", StateEnum.Unstart))
    steps.append((StepEnum.PRE_FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.MACRO_PLACEMENT, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.POST_FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "dreamplace", StateEnum.Unstart))
    steps.append((SkippableStepEnum.TIMING_OPT, "sizer", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.RCX, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.STA, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LVS, "ecc", StateEnum.Unstart))
    steps.append((SkippableStepEnum.POST_ROUTE_LEC, "yosys_lec", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.HARDEN, "ecc", StateEnum.Unstart))

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
        "floor": StepEnum.POST_FLOORPLAN.value,
        "macro": StepEnum.MACRO_PLACEMENT.value,
        "macroplace": StepEnum.MACRO_PLACEMENT.value,
        "macroplacement": StepEnum.MACRO_PLACEMENT.value,
        "postfloorplan": StepEnum.POST_FLOORPLAN.value,
        "place": StepEnum.PLACEMENT.value,
        "placement": StepEnum.PLACEMENT.value,
        "cts": StepEnum.CTS.value,
        "legal": StepEnum.LEGALIZATION.value,
        "legalization": StepEnum.LEGALIZATION.value,
        "timingopt": SkippableStepEnum.TIMING_OPT.value,
        "timingoptimization": SkippableStepEnum.TIMING_OPT.value,
        "route": StepEnum.ROUTING.value,
        "routing": StepEnum.ROUTING.value,
        "drc": StepEnum.DRC.value,
        "lvs": StepEnum.LVS.value,
        "filler": StepEnum.FILLER.value,
        "lec": SkippableStepEnum.LEC.value,
        "postlec": SkippableStepEnum.POST_ROUTE_LEC.value,
        "postroutelec": SkippableStepEnum.POST_ROUTE_LEC.value,
        "rcx": StepEnum.RCX.value,
        "sta": StepEnum.STA.value,
        "harden": StepEnum.HARDEN.value,
    }
    return aliases.get(alias_key, token)


def build_flow_range(
    from_step: str | StepBaseEnum,
    to_step: str | StepBaseEnum,
    *,
    skip: Collection[str] = (),
) -> list:
    """Return the inclusive canonical RTL-to-GDS range requested by a workspace.

    The RTL-to-GDS chain is owned by :func:`build_rtl2gds_flow`; partial flows
    are always slices of that chain rather than a second hand-maintained list.
    Skipped steps are excluded from the chain first, so a skipped step cannot
    serve as a range boundary (it is unknown in the filtered chain).
    """
    steps = build_rtl2gds_flow(skip=skip)
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

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))

    return steps


def build_synthesis_lec_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    steps.append((SkippableStepEnum.LEC, "yosys_lec", StateEnum.Unstart))

    return steps


def get_flow_builders() -> dict[str, Callable[[], list]]:
    """Discover flow presets from the build_*_flow defs in this module."""
    builders = {}
    for name, fn in globals().items():
        if not (callable(fn) and name.startswith("build_") and name.endswith("_flow")):
            continue
        preset = name[len("build_") : -len("_flow")]
        if preset:
            builders[preset] = fn
    return builders
