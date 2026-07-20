from __future__ import annotations

from chipcompiler.data import Checklist, CheckState, Workspace, WorkspaceStep


class SizerChecklist:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        self.build_checklist()

    def build_checklist(self) -> list:
        checklist = Checklist(path=self.workspace_step.checklist.path or "")
        checklist.save()
        rows = checklist.data.get("checklist", [])
        self.workspace_step.checklist.checklist = rows
        return rows

    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.path or "")
        return checklist.save()

    def update_item(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
    ) -> None:
        checklist = Checklist(path=self.workspace_step.checklist.path or "")
        checklist.update(step=step, type=type, item=item, state=state)

    def check(self) -> None:
        pass
