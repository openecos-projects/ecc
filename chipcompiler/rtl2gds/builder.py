#!/usr/bin/env python
from collections.abc import Callable

from chipcompiler.data import StateEnum, StepEnum


def build_rtl2gds_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    steps.append((StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "dreamplace", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LVS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "ecc", StateEnum.Unstart))

    return steps


def build_syn_sta_flow() -> list:
    steps = []

    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))

    return steps


def build_harden_flow() -> list:
    steps = build_rcx_flow()

    steps.append((StepEnum.HARDEN, "ecc", StateEnum.Unstart))

    return steps


def build_rcx_flow() -> list:
    steps = build_rtl2gds_flow()

    steps.append((StepEnum.RCX, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.STA, "ecc", StateEnum.Unstart))

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
