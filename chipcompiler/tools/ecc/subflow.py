#!/usr/bin/env python
from enum import Enum

from chipcompiler.data import StepEnum, step_from_value
from chipcompiler.tools.subflow import SubFlow


class EccSubFlowEnum(Enum):
    load_data = "load data"
    save_data = "save data"
    analysis = "analysis"
    init_floorplan = "init floorplan"
    macro_place = "macro placement"
    create_tracks = "create tracks"
    place_io_pins = "place io pins"
    tap_cell = "tap cell"
    PDN = "PDN"
    set_clock_net = "set clock net"
    run_placement = "run placement"
    run_diff_sizing = "run diff sizing"
    run_CTS = "run CTS"
    run_legalization = "run legalization"
    run_routing = "run routing"
    run_filler = "run filler"
    run_DRC = "run DRC"
    check_antenna = "check antenna"
    run_LVS = "run LVS"
    run_harden = "run harden"
    run_rcx = "run rcx"
    run_sta = "run sta"
    run_power_analysis = "run power analysis"
    run_emir = "run EMIR"


# Stages of each ECC step, in execution order. Steps absent here have no sub-flow.
_STAGES: dict[StepEnum, tuple[EccSubFlowEnum, ...]] = {
    StepEnum.PRE_FLOORPLAN: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.set_clock_net,
        EccSubFlowEnum.init_floorplan,
        EccSubFlowEnum.save_data,
    ),
    StepEnum.MACRO_PLACEMENT: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.macro_place,
        EccSubFlowEnum.save_data,
    ),
    StepEnum.POST_FLOORPLAN: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.create_tracks,
        EccSubFlowEnum.place_io_pins,
        EccSubFlowEnum.tap_cell,
        EccSubFlowEnum.PDN,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.PLACEMENT: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_placement,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.DIFF_SIZING: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_diff_sizing,
        EccSubFlowEnum.save_data,
    ),
    StepEnum.CTS: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_CTS,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.LEGALIZATION: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_legalization,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.ROUTING: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_routing,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.FILLER: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_filler,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.DRC: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_DRC,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.LVS: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_LVS,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.ANTENNA_CHECK: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.check_antenna,
        EccSubFlowEnum.save_data,
    ),
    StepEnum.HARDEN: (EccSubFlowEnum.load_data, EccSubFlowEnum.run_harden),
    StepEnum.RCX: (EccSubFlowEnum.load_data, EccSubFlowEnum.run_rcx),
    StepEnum.STA: (EccSubFlowEnum.load_data, EccSubFlowEnum.run_sta),
    StepEnum.POWER_ANALYSIS: (
        EccSubFlowEnum.load_data,
        EccSubFlowEnum.run_power_analysis,
        EccSubFlowEnum.save_data,
        EccSubFlowEnum.analysis,
    ),
    StepEnum.EMIR: (EccSubFlowEnum.load_data, EccSubFlowEnum.run_emir, EccSubFlowEnum.save_data),
}


class EccSubFlow(SubFlow):
    def stages(self) -> tuple[str, ...]:
        step = step_from_value(self.workspace_step.name)
        return tuple(stage.value for stage in _STAGES.get(step, ()))

    def build_sub_flow(self) -> list:
        # An already-populated sub-flow (for example from an earlier run in
        # this process) is kept as is.
        if len(self.workspace_step.subflow.steps or []) > 0:
            return self.workspace_step.subflow.steps
        return super().build_sub_flow()
