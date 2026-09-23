#!/usr/bin/env python
from chipcompiler.data import LECEngineEnum
from chipcompiler.tools.lec_subflow import LecSubFlow


class LecDualSubFlow(LecSubFlow):
    """Aggregate subflow: one stage per physical engine plus analysis.

    Child engine threads never touch this subflow (their own per-engine
    subflows record the detail); the dual runner owns it and records
    per-engine final states only.
    """

    STAGES = (
        *(f"run lec ({engine.value})" for engine in LECEngineEnum.DUAL.spawn_engines),
        "analysis",
    )

    @staticmethod
    def stage_name(engine: LECEngineEnum) -> str:
        return f"run lec ({engine.value})"
