#!/usr/bin/env python

from chipcompiler.data import StateEnum, StepEnum


def build_rtl2gds_flow() -> list:
    steps = []
    
    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))        
    steps.append((StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "ecc", StateEnum.Unstart))
    
    return steps
