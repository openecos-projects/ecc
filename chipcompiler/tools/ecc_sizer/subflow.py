from enum import Enum

from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.tools.subflow import SubFlow, stage_template


class SizerSubFlowEnum(Enum):
    run_sizer = "run sizer"
    run_preplace = "run preplace"
    run_legalization = "run legalization"
    save_data = "save data"


class SizerSubFlow(SubFlow):
    """Sub-flow of a sizer step.

    Unlike the other tools it rebuilds its stages on every construction, and a
    rebuild invalidates this step and every later one in the flow, so a changed
    stage list never leaves stale results downstream.
    """

    def init_sub_flow(self) -> None:
        from chipcompiler.utility import json_read

        data = json_read(self.workspace_step.subflow.path or "")
        if len(data) > 0:
            self.workspace_step.subflow.steps = data.get("steps", [])
        self.build_sub_flow()

    def stages(self) -> tuple[str, ...]:
        if self.workspace_step.name == StepEnum.PREPLACE.value:
            stages = (SizerSubFlowEnum.run_preplace, SizerSubFlowEnum.save_data)
        else:
            stages = (
                SizerSubFlowEnum.run_sizer,
                SizerSubFlowEnum.run_legalization,
                SizerSubFlowEnum.save_data,
            )
        return tuple(stage.value for stage in stages)

    def _current_stage_names(self) -> list:
        return [step_dict.get("name") for step_dict in self.workspace_step.subflow.steps or []]

    def build_sub_flow(self) -> list[dict]:
        if self._current_stage_names() != list(self.stages()):
            self.workspace_step.subflow.steps = [stage_template(name) for name in self.stages()]
            self.save()
            self._invalidate_owner_and_suffix()
        return self.workspace_step.subflow.steps

    def _invalidate_owner_and_suffix(self) -> None:
        steps = self.workspace.flow.data.get("steps", [])
        start = next(
            (
                index
                for index, step in enumerate(steps)
                if isinstance(step, dict)
                and step.get("name") == self.workspace_step.name
                and step.get("tool") == self.workspace_step.tool
            ),
            None,
        )
        if start is None:
            return
        for step in steps[start:]:
            if not isinstance(step, dict):
                continue
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0
        if self.workspace.flow.path is None:
            return
        from chipcompiler.utility import json_write

        json_write(self.workspace.flow.path, self.workspace.flow.data)

    def reset_stages(self) -> list[dict]:
        if self._current_stage_names() != list(self.stages()):
            self.workspace_step.subflow.steps = [stage_template(name) for name in self.stages()]
        else:
            for step_dict in self.workspace_step.subflow.steps or []:
                step_dict["state"] = StateEnum.Unstart.value
                step_dict["runtime"] = ""
                step_dict["peak memory (mb)"] = 0
                step_dict["info"] = {}
        self.save()
        return self.workspace_step.subflow.steps
