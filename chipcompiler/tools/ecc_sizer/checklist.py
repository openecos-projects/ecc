from __future__ import annotations

from chipcompiler.data import Checklist, CheckState, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist


class SizerChecklist:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        self.build_checklist()

    def build_checklist(self) -> list:
        refresh_step_checklist(self.workspace, self.workspace_step)
        return self.workspace_step.checklist["checklist"]

    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        return checklist.save()

    def update_item(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
    ) -> None:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        checklist.update(step=step, type=type, item=item, state=state)

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)
