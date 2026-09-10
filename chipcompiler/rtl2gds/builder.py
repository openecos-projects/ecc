#!/usr/bin/env python
from collections.abc import Callable

from chipcompiler.data import StateEnum, StepEnum


def build_rtl2gds_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    steps.append((StepEnum.LEC, "yosys_lec", StateEnum.Unstart))
    steps.append((StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.TIMING_OPT, "sizer", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.RCX, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.STA, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LVS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.POST_ROUTE_LEC, "yosys_lec", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.HARDEN, "ecc", StateEnum.Unstart))

    return steps


def normalize_flow_step(value: str | StepEnum) -> str:
    """Resolve a CLI/manifest step spelling to its canonical flow name."""
    if isinstance(value, StepEnum):
        return value.value
    token = str(value or "").strip()
    if not token:
        return ""
    alias_key = token.lower().replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "synth": StepEnum.SYNTHESIS.value,
        "synthesis": StepEnum.SYNTHESIS.value,
        "floor": StepEnum.FLOORPLAN.value,
        "floorplan": StepEnum.FLOORPLAN.value,
        "place": StepEnum.PLACEMENT.value,
        "placement": StepEnum.PLACEMENT.value,
        "cts": StepEnum.CTS.value,
        "legal": StepEnum.LEGALIZATION.value,
        "legalization": StepEnum.LEGALIZATION.value,
        "timingopt": StepEnum.TIMING_OPT.value,
        "timingoptimization": StepEnum.TIMING_OPT.value,
        "route": StepEnum.ROUTING.value,
        "routing": StepEnum.ROUTING.value,
        "drc": StepEnum.DRC.value,
        "lvs": StepEnum.LVS.value,
        "filler": StepEnum.FILLER.value,
        "lec": StepEnum.LEC.value,
        "postlec": StepEnum.POST_ROUTE_LEC.value,
        "postroutelec": StepEnum.POST_ROUTE_LEC.value,
        "rcx": StepEnum.RCX.value,
        "sta": StepEnum.STA.value,
        "harden": StepEnum.HARDEN.value,
    }
    return aliases.get(alias_key, token)


def build_flow_range(from_step: str | StepEnum, to_step: str | StepEnum) -> list:
    """Return the inclusive canonical RTL-to-GDS range requested by a workspace.

    The RTL-to-GDS chain is owned by :func:`build_rtl2gds_flow`; partial flows
    are always slices of that chain rather than a second hand-maintained list.
    """
    steps = build_rtl2gds_flow()
    names = [
        step.value if isinstance(step, StepEnum) else str(step) for step, _tool, _state in steps
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
    steps.append((StepEnum.LEC, "yosys_lec", StateEnum.Unstart))

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
