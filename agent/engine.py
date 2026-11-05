import logging
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum, WorkspaceStep
from chipcompiler.data.step import next_step_index
from chipcompiler.engine.flow import EngineFlow


def _is_candidate_workspace(workspace) -> bool:
    root = Path(workspace.directory).resolve()
    return root.parent.name == "candidates" and root.parent.parent.name == ".agent"


def _wait_for_step_rendered(observer, workspace_step: WorkspaceStep, state: StateEnum) -> bool:
    if observer is None or state != StateEnum.Success:
        return True
    callback = getattr(observer, "wait_for_step_rendered", None)
    if not callable(callback):
        return True
    try:
        return bool(callback(workspace_step, state))
    except Exception:
        # Fail-open: observer bugs must not invalidate successful tool results.
        logging.getLogger(__name__).exception("flow observer render gate failed")
        return True


class AgentEngineFlow(EngineFlow):
    step_worker_module = "agent.step_worker"

    def build_default_steps(self):
        super().build_default_steps()
        steps = self.workspace.flow.data.get("steps", [])
        if any(step["name"].casefold() == StepEnum.DRC.value for step in steps):
            return
        filler_index = next(index for index, step in enumerate(steps) if step["name"] == "filler")
        steps.insert(
            filler_index,
            self.init_flow_step(
                StepEnum.DRC.value, "ecc", StateEnum.Unstart, index=next_step_index(steps)
            ),
        )
        self.save()

    def _should_save_layout_image(self) -> bool:
        return not _is_candidate_workspace(self.workspace)

    def run_step(
        self,
        workspace_step: WorkspaceStep,
        *,
        rerun: bool = False,
        observer=None,
    ) -> StateEnum:
        state = super().run_step(workspace_step, rerun=rerun, observer=observer)
        if state == StateEnum.Success and not _wait_for_step_rendered(
            observer, workspace_step, state
        ):
            return StateEnum.Invalid
        return state
