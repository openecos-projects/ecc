import os
import time
from enum import Enum

from chipcompiler.data import StateEnum, Workspace, WorkspaceStep


class SizerSubFlowEnum(Enum):
    run_sizer = "run sizer"
    run_legalization = "run legalization"
    save_data = "save data"


class SizerSubFlow:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        self.init_sub_flow()
        self.start_time = time.time()
        self.start_memory = self.get_peak_memory()

    def init_sub_flow(self) -> None:
        from chipcompiler.utility import json_read

        data = json_read(self.workspace_step.subflow.path or "")
        if len(data) > 0:
            self.workspace_step.subflow.steps = data.get("steps", [])
        self.build_sub_flow()

    def _canonical_steps(self) -> list[dict]:
        return [
            {
                "name": stage.value,
                "state": StateEnum.Unstart.value,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
            for stage in SizerSubFlowEnum
        ]

    def build_sub_flow(self) -> list[dict]:
        expected = [stage.value for stage in SizerSubFlowEnum]
        current = [step_dict.get("name") for step_dict in self.workspace_step.subflow.steps or []]
        if current != expected:
            self.workspace_step.subflow.steps = self._canonical_steps()
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
        expected = [stage.value for stage in SizerSubFlowEnum]
        current = [step_dict.get("name") for step_dict in self.workspace_step.subflow.steps or []]
        if current != expected:
            self.workspace_step.subflow.steps = self._canonical_steps()
        else:
            for step_dict in self.workspace_step.subflow.steps or []:
                step_dict["state"] = StateEnum.Unstart.value
                step_dict["runtime"] = ""
                step_dict["peak memory (mb)"] = 0
                step_dict["info"] = {}
        self.save()
        return self.workspace_step.subflow.steps

    def save(self) -> bool:
        from chipcompiler.utility import json_write

        subflow = self.workspace_step.subflow
        data = {
            "path": str(subflow.path) if subflow.path else "",
            "steps": subflow.steps,
        }
        return json_write(file_path=subflow.path or "", data=data)

    def get_runtime(self) -> str:
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        runtime = f"{hours}:{minutes}:{seconds}"
        self.start_time = end_time
        return runtime

    def get_peak_memory(self) -> float:
        pid = os.getpid()
        peak_memory = 0

        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as file:
                for line in file:
                    if line.startswith("VmRSS:"):
                        peak_memory = int(line.split()[1]) / 1024
                        break
        except (OSError, ValueError):
            pass

        return peak_memory

    def update_step(
        self,
        step_name: str,
        state: str | StateEnum,
        info: dict | None = None,
    ) -> None:
        state = state.value if isinstance(state, StateEnum) else state
        info = info or {}
        runtime = self.get_runtime()
        peak_memory = self.get_peak_memory() - self.start_memory
        peak_memory = 0 if peak_memory < 0 else round(peak_memory, 3)

        for step_dict in self.workspace_step.subflow.steps or []:
            if step_dict.get("name") == step_name:
                step_dict["state"] = state
                step_dict["runtime"] = runtime
                step_dict["peak memory (mb)"] = peak_memory
                step_dict["info"] = info
                self.save()

                from chipcompiler.runtime.subflow_events import publish_subflow_stage

                publish_subflow_stage(self.workspace, self.workspace_step, step_dict)

                break
