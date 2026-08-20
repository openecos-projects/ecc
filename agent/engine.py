from chipcompiler.data import StateEnum, WorkspaceStep
from chipcompiler.engine.flow import EngineFlow

from .tools import run_step as run_agent_step


class AgentEngineFlow(EngineFlow):
    """Flow Agent engine: the canonical step lifecycle lives in EngineFlow;
    only the tool runner and the agent's result vocabulary differ."""

    def build_default_steps(self):
        super().build_default_steps()
        steps = self.workspace.flow.data["steps"]
        if any(step["name"] == "DRC" for step in steps):
            return
        filler_index = next(index for index, step in enumerate(steps) if step["name"] == "filler")
        steps.insert(filler_index, self.init_flow_step("DRC", "ecc", StateEnum.Unstart))
        self.save()

    def _invoke_step_tool(self, workspace_step: WorkspaceStep):
        return run_agent_step(
            workspace=self.workspace, step=workspace_step, ecc_module=self.engine_db.engine
        )

    def _derive_step_state(
        self, workspace_step: WorkspaceStep, result, *, raised: bool
    ) -> StateEnum:
        if raised:
            return StateEnum.Imcomplete
        if result is StateEnum.Invalid:
            return StateEnum.Invalid
        if result is True or result is StateEnum.Success:
            return (
                StateEnum.Success
                if self.check_step_result(workspace_step=workspace_step)
                else StateEnum.Imcomplete
            )
        return StateEnum.Imcomplete
