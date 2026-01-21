#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.data import (
    StepEnum,
    StateEnum
)

def build_rtl2gds_flow() -> list:
    steps = []
    
    steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))        
    steps.append((StepEnum.FLOORPLAN, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.NETLIST_OPT, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "iEDA", StateEnum.Unstart))
    
    return steps
