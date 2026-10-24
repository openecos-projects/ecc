from copy import deepcopy
from enum import Enum

from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.data.workspace.flow_ledger import ledger_lock, save_ledger
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
        """Rebuild the stage list, resetting the ledger before writing stages.

        The ledger is authoritative, so it is committed first: a failed ledger
        write aborts the rebuild and leaves both the workspace step and
        ``subflow.json`` untouched. A failed ``subflow.json`` write after a
        committed ledger reset is the conservative state (downstream steps
        rerun) and is reported by the writer.
        """
        if self._current_stage_names() != list(self.stages()):
            previous_stages = list(self.workspace_step.subflow.steps or [])
            self.workspace_step.subflow.steps = [stage_template(name) for name in self.stages()]
            if not self._invalidate_owner_and_suffix():
                self.workspace_step.subflow.steps = previous_stages
                raise RuntimeError(
                    f"Failed to persist the flow reset for {self.workspace_step.name}"
                )
            # Stage reset deliberately touches only subflow.json; the step's own
        # ledger state is reset through the flow API by the caller.
        self.save()
        return self.workspace_step.subflow.steps

    def _invalidate_owner_and_suffix(self) -> bool:
        """Mark this step and every later one unstarted in the ledger.

        Returns False (restoring the ledger in memory) when the write fails, so
        memory and disk keep describing the same flow.
        """
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
            return True
        with ledger_lock(self.workspace.flow):
            previous_data = deepcopy(self.workspace.flow.data)
            for step in steps[start:]:
                if not isinstance(step, dict):
                    continue
                step["state"] = StateEnum.Unstart.value
                step["runtime"] = ""
                step["peak memory (mb)"] = 0
            if not save_ledger(self.workspace.flow):
                self.workspace.flow.data = previous_data
                logger = getattr(self.workspace, "logger", None)
                if logger is not None:
                    logger.error(
                        "Failed to persist the flow reset for %s", self.workspace_step.name
                    )
                return False
            return True

    def reset_stages(self) -> list[dict]:
        if self._current_stage_names() != list(self.stages()):
            self.workspace_step.subflow.steps = [stage_template(name) for name in self.stages()]
        else:
            for step_dict in self.workspace_step.subflow.steps or []:
                step_dict["state"] = StateEnum.Unstart.value
                step_dict["runtime"] = ""
                step_dict["peak memory (mb)"] = 0
                step_dict["info"] = {}
        # Stage reset deliberately touches only subflow.json; the step's own
        # ledger state is reset through the flow API by the caller.
        self.save()
        return self.workspace_step.subflow.steps
