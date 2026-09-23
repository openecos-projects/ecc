#!/usr/bin/env python
from chipcompiler.data import LECEngineEnum, StateEnum
from chipcompiler.tools.kepler_formal.subflow import KeplerFormalSubFlow


class LecDualSubFlow(KeplerFormalSubFlow):
    """Aggregate subflow: one stage per physical engine plus analysis.

    Child engine threads never touch this subflow (their own per-engine
    subflows record the detail); the dual runner owns it and records
    per-engine final states only.
    """

    @staticmethod
    def stage_name(engine: LECEngineEnum) -> str:
        return f"run lec ({engine.value})"

    def build_sub_flow(self) -> list:
        def subflow_template(step_name: str):
            return {
                "name": step_name,
                "state": StateEnum.Unstart.value,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }

        self.workspace_step.subflow.steps = [
            *(
                subflow_template(self.stage_name(engine))
                for engine in LECEngineEnum.DUAL.spawn_engines
            ),
            subflow_template("analysis"),
        ]
        self.save()
        return self.workspace_step.subflow.steps
