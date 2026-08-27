#!/usr/bin/env python
import time
from enum import Enum

from chipcompiler.data import StateEnum, StepEnum, Workspace, WorkspaceStep


class EccSubFlowEnum(Enum):
    load_data = "load data"
    save_data = "save data"
    analysis = "analysis"
    init_floorplan = "init floorplan"
    create_tracks = "create tracks"
    place_io_pins = "place io pins"
    tap_cell = "tap cell"
    PDN = "PDN"
    set_clock_net = "set clock net"
    run_net_optimization = "run net optimization"
    run_macro_placement = "run macro placement"
    run_placement = "run placement"
    run_CTS = "run CTS"
    run_legalization = "run legalization"
    run_routing = "run routing"
    run_filler = "run filler"
    run_DRC = "run DRC"
    run_LVS = "run LVS"
    run_harden = "run harden"
    run_rcx = "run rcx"
    run_sta = "run sta"


class EccSubFlow:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step

        self.init_sub_flow()

        # set start time
        self.start_time = time.time()

        # set start memory
        self.start_memory = self.get_peak_memory()

    def init_sub_flow(self):
        from chipcompiler.utility import json_read

        data = json_read(self.workspace_step.subflow.path or "")
        if len(data) > 0:
            self.workspace_step.subflow.steps = data.get("steps", [])
        else:
            self.build_sub_flow()

    def build_sub_flow(self) -> list:
        if len(self.workspace_step.subflow.steps or []) > 0:
            return self.workspace_step.subflow.steps

        def subflow_template(step_name: str):
            return {
                "name": step_name,  # step name
                "state": StateEnum.Unstart.value,  # step state
                "runtime": "",  # step run time
                "peak memory (mb)": 0,  # step peak memory
                "info": {},  # step additional infomation
            }

        steps = []

        step = StepEnum(self.workspace_step.name)
        match step:
            case StepEnum.FLOORPLAN:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.init_floorplan.value))
                steps.append(subflow_template(EccSubFlowEnum.create_tracks.value))
                steps.append(subflow_template(EccSubFlowEnum.place_io_pins.value))
                steps.append(subflow_template(EccSubFlowEnum.tap_cell.value))
                steps.append(subflow_template(EccSubFlowEnum.PDN.value))
                steps.append(subflow_template(EccSubFlowEnum.set_clock_net.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.NETLIST_OPT:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.set_clock_net.value))
                steps.append(subflow_template(EccSubFlowEnum.run_net_optimization.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.PLACEMENT:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_placement.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.MACRO_PLACEMENT:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_macro_placement.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.CTS:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_CTS.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.LEGALIZATION:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_legalization.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.ROUTING:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_routing.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.FILLER:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_filler.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.DRC:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_DRC.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))
            case StepEnum.LVS:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_LVS.value))
                steps.append(subflow_template(EccSubFlowEnum.save_data.value))
                steps.append(subflow_template(EccSubFlowEnum.analysis.value))

            case StepEnum.HARDEN:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_harden.value))

            case StepEnum.RCX:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_rcx.value))

            case StepEnum.STA:
                steps.append(subflow_template(EccSubFlowEnum.load_data.value))
                steps.append(subflow_template(EccSubFlowEnum.run_sta.value))

        self.workspace_step.subflow.steps = steps

        self.save()

    def save(self) -> bool:
        from chipcompiler.utility import json_write

        subflow = self.workspace_step.subflow
        data = {
            "path": str(subflow.path) if subflow.path else "",
            "steps": subflow.steps,
        }
        return json_write(file_path=subflow.path or "", data=data)

    def get_runtime(self):
        # end time
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        runtime = (
            f"{int(elapsed_time // 3600)}:"
            f"{int((elapsed_time % 3600) // 60)}:{int(elapsed_time % 60)}"
        )

        # reset start time
        self.start_time = end_time

        return runtime

    def get_peak_memory(self):
        import os

        # Get current process ID
        pid = os.getpid()
        peak_memory = 0

        try:
            # Read memory usage from /proc/{pid}/status
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # VmRSS is in kB
                        rss_kb = int(line.split()[1])
                        # Convert to MB
                        peak_memory = rss_kb / 1024
                        break
        except (OSError, ValueError):
            # Ignore errors, return 0 if failed
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
