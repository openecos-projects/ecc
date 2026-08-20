#!/usr/bin/env python

import logging
import os

from chipcompiler.data import EccOutput, StateEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.engine import EngineDB
from chipcompiler.engine.runner import EngineFlowRunner
from chipcompiler.engine.signoff import (
    SignoffPackageCollector,
    SignoffPackageOptions,
    SignoffPackageResult,
)

logger = logging.getLogger(__name__)


_GEOMETRY_SNAPSHOT_STEPS = frozenset(
    {
        StepEnum.FLOORPLAN.value,
        StepEnum.NETLIST_OPT.value,
        StepEnum.PLACEMENT.value,
        StepEnum.CTS.value,
        StepEnum.TIMING_OPT.value,
        StepEnum.LEGALIZATION.value,
        StepEnum.ROUTING.value,
        StepEnum.DRC.value,
        StepEnum.LVS.value,
        StepEnum.FILLER.value,
    }
)


class EngineFlow(EngineFlowRunner):
    def __init__(self, workspace: Workspace, engine_db: EngineDB = None):
        self.workspace = workspace
        self.workspace_steps = []
        self.engine_db = engine_db  # db engine for this flow

        if self.workspace is not None:
            self.load()

    def build_default_steps(self):
        # Flow step sequences
        steps = []

        steps.append(self.init_flow_step(StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.PLACEMENT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.CTS, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.LEGALIZATION, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.ROUTING, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FILLER, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.GDS, "klayout", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.SIGNOFF, "ecc", StateEnum.Unstart))

        self.workspace.flow.data = {"steps": steps}

        self.save()

    def has_init(self):
        return self.workspace is not None and len(self.workspace.flow.data.get("steps", [])) > 0

    def init_flow_step(self, step: StepEnum | str, tool: str, state: str | StateEnum):
        step_value = step.value if isinstance(step, StepEnum) else step
        state_value = state.value if isinstance(state, StateEnum) else state
        return {
            "name": step_value,  # step name
            "tool": tool,  # eda tool name
            "state": state_value,  # step state
            "runtime": "",  # step run time
            "peak memory (mb)": 0,  # step peak memory
            "info": {},  # step additional infomation
        }

    def add_step(self, step: StepEnum | str, tool: str, state: str | StateEnum):
        steps = self.workspace.flow.data.get("steps", [])
        steps.append(self.init_flow_step(step, tool, state))

        self.workspace.flow.data = {"steps": steps}

        self.save()

    def load(self) -> bool:
        """
        load flow config json from workspace
        """
        from chipcompiler.utility import json_read

        if not self.workspace.flow.path:
            self.workspace.flow.data = {}
            return False
        self.workspace.flow.data = json_read(self.workspace.flow.path)
        return len(self.workspace.flow.data.get("steps", [])) > 0

    def save(self) -> bool:
        """
        save flow to workspace json
        """
        from chipcompiler.utility import json_write

        return json_write(self.workspace.flow.path, self.workspace.flow.data)

    def get_step(self, name: str, tool: str):
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                return step

        return None

    def get_workspace_step(self, name: str) -> WorkspaceStep | None:
        for workspace_step in self.workspace_steps:
            if workspace_step.name == name:
                return workspace_step

        return None

    def check_state(self, name: str, tool: str, state: str | StateEnum):
        """
        return True if step state has been set
        """
        step = self.get_step(name, tool)
        state_value = state.value if isinstance(state, StateEnum) else state
        return step is not None and step.get("state") == state_value

    def set_state(
        self,
        name: str,
        tool: str,
        state: str | StateEnum,
        runtime: str = None,
        peak_memory: float = None,
    ) -> bool:
        state_value = state.value if isinstance(state, StateEnum) else state
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                step["state"] = state_value
                if runtime is not None:
                    step["runtime"] = runtime
                if peak_memory is not None:
                    step["peak memory (mb)"] = peak_memory

                if not self.save():
                    logger.error(
                        "Failed to persist flow state for %s/%s (state=%s); "
                        "state change exists only in memory",
                        name,
                        tool,
                        state_value,
                    )
                    return False
                return True

        return False

    def clear_states(self):
        from chipcompiler.data import StateEnum

        for step in self.workspace.flow.data.get("steps", []):
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0

        self.save()

    def is_flow_success(self):
        """
        check all steps success
        """
        from chipcompiler.data import StateEnum

        for step in self.workspace.flow.data.get("steps", []):
            if step["state"] != StateEnum.Success.value:
                return False

        return True

    def check_step_result(self, workspace_step: WorkspaceStep):
        """
        check step output exist
        """

        success = False
        output = workspace_step.output
        # HARDEN/RCX/GDS results live on the place-and-route (ecc) output leaves.
        ecc_output = output if isinstance(output, EccOutput) else None
        match workspace_step.name:
            case StepEnum.SYNTHESIS.value:
                if os.path.exists(output.verilog or ""):
                    success = True
            case StepEnum.HARDEN.value:
                if (
                    ecc_output
                    and os.path.exists(ecc_output.lef or "")
                    and os.path.exists(ecc_output.lib or "")
                ):
                    success = True
            case StepEnum.LVS.value:
                if (
                    ecc_output
                    and os.path.exists(output.def_ or "")
                    and os.path.exists(output.verilog or "")
                    and os.path.exists(output.gds or "")
                    and os.path.exists(workspace_step.report.step or "")
                    and os.path.exists(workspace_step.feature.step or "")
                ):
                    success = True
            case StepEnum.RCX.value:
                success = True
                for spef in ecc_output.spef if ecc_output else []:
                    if not os.path.exists(spef):
                        success = False
                        break
            case StepEnum.TIMING_OPT.value:
                if os.path.exists(output.def_ or "") and os.path.exists(output.verilog or ""):
                    success = True
            case _:
                gds = ecc_output.gds if ecc_output else None
                if (
                    os.path.exists(output.def_ or "")
                    and os.path.exists(output.verilog or "")
                    and os.path.exists(gds or "")
                ):
                    success = True
        if success and workspace_step.name in _GEOMETRY_SNAPSHOT_STEPS:
            geometry_manifest = ecc_output.geometry_manifest if ecc_output else None
            # Unit callers may construct a minimal EccOutput without a geometry
            # destination. Real physical flow steps declare one in their builder;
            # when declared, it is part of the success contract.
            return geometry_manifest is None or geometry_manifest.is_file()
        return success

    def collect_signoff_package(
        self,
        options: SignoffPackageOptions | None = None,
    ) -> SignoffPackageResult:
        """
        Collect harden-flow signoff resources from this flow workspace.
        """
        return SignoffPackageCollector(self.workspace).collect(options)

    def create_step_workspaces(self, *, executable_steps: set[str] | None = None):
        """
        create all step workspaces

        executable_steps: names of the steps that will actually run. Only those
        steps verify tool dependencies; other steps are always built so the
        input/output chaining stays intact when a non-selected tool is absent.
        """
        self.workspace_steps = []
        pre_step = None
        for step in self.workspace.flow.data.get("steps", []):
            if pre_step is None:
                # use the origin def and verilog in workspace for the first step.
                input_def = self.workspace.design.origin_def
                input_verilog = self.workspace.design.origin_verilog
                input_db = None
            else:
                # use the output def and verilog from last step.
                input_def = pre_step.output.def_
                input_verilog = pre_step.output.verilog
                input_db = pre_step.output.db

            from chipcompiler.tools import create_step

            # create workspace step
            eda_step = create_step(
                workspace=self.workspace,
                step=step["name"],
                eda=step["tool"],
                input_def=input_def,
                input_verilog=input_verilog,
                input_db=input_db,
                initialize_config=True,
                check_dependency=executable_steps is None or step["name"] in executable_steps,
            )
            # save workspace step
            if eda_step is not None:
                if (
                    pre_step is not None
                    and pre_step.name == StepEnum.RCX.value
                    and eda_step.name == StepEnum.STA.value
                    and isinstance(eda_step.output, EccOutput)
                    and isinstance(pre_step.output, EccOutput)
                ):
                    eda_step.output.spef = pre_step.output.spef
                self.workspace_steps.append(eda_step)
                pre_step = eda_step
            else:
                step["state"] = StateEnum.Imcomplete.value
                logger.error(
                    "Failed to create step workspace for %s (tool=%s); "
                    "step marked Incomplete, remaining steps will not be created",
                    step.get("name", step),
                    step.get("tool", "?"),
                )
                self.save()
                break

    def init_db_engine(self) -> bool:
        if len(self.workspace_steps) <= 0:
            return False

        # check ecc is initialized by last step, if exist and success,
        # use it to init db engine directly.
        if self.engine_db is None:
            self.engine_db = EngineDB(workspace=self.workspace)
        else:
            if self.engine_db.has_init():
                return True

        # init engine step by last workpsace step data if all step run success
        workspace_step = None
        for ws_step in self.workspace_steps:
            if not self.check_state(name=ws_step.name, tool=ws_step.tool, state=StateEnum.Success):
                # use the first unsuccess step to setup db engine
                workspace_step = ws_step
                break

        return self.engine_db.create_db_engine(step=workspace_step)
