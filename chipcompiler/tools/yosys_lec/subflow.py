#!/usr/bin/env python
import time

from chipcompiler.data import StateEnum, Workspace, WorkspaceStep


class YosysLecSubFlow:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        self.init_sub_flow()
        self.start_time = time.time()
        self.start_memory = self.get_peak_memory()

    def init_sub_flow(self):
        from chipcompiler.utility import json_read

        data = json_read(self.workspace_step.subflow.path or "")
        if len(data) > 0:
            self.workspace_step.subflow.steps = data.get("steps", [])
        else:
            self.build_sub_flow()

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
            subflow_template("run lec"),
            subflow_template("analysis"),
        ]
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

    def get_runtime(self):
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        runtime = (
            f"{int(elapsed_time // 3600)}:"
            f"{int((elapsed_time % 3600) // 60)}:{int(elapsed_time % 60)}"
        )
        self.start_time = end_time
        return runtime

    def get_peak_memory(self):
        import os

        peak_memory = 0
        try:
            with open(f"/proc/{os.getpid()}/status") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        peak_memory = int(line.split()[1]) / 1024
                        break
        except (OSError, ValueError):
            pass
        return peak_memory

    def update_step(self, step_name: str, state: str | StateEnum, info: dict | None = None):
        if info is None:
            info = {}
        state = state.value if isinstance(state, StateEnum) else state
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
