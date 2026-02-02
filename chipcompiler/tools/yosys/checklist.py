#!/usr/bin/env python
from chipcompiler.data import CheckState, Workspace, WorkspaceStep


class YosysChecklist:
    def __init__(self, workspace: Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step

        self.init_checklist()

    def init_checklist(self):
        from chipcompiler.utility import json_read

        data = json_read(self.workspace_step.checklist.get("path", ""))
        if len(data) > 0:
            self.workspace_step.checklist["checklist"] = data.get("checklist", [])
        else:
            self.build_checklist()

    def build_checklist(self) -> list:
        def checklist_template(check_item: str, description: str):
            return {
                "name": check_item,
                "description": description,
                "state": CheckState.Unstart.value,
            }

        checklist = []

        checklist.append(checklist_template(check_item="check_item_1", description="check item 1"))
        checklist.append(checklist_template(check_item="check_item_2", description="check item 2"))

        self.workspace_step.checklist["checklist"] = checklist

        self.save()

    def save(self) -> bool:
        from chipcompiler.utility import json_write

        return json_write(
            file_path=self.workspace_step.checklist.get("path", ""),
            data=self.workspace_step.checklist,
        )

    def update_item(self, check_item: str, state: str | CheckState):
        state = state.value if isinstance(state, CheckState) else state

        for item_dict in self.workspace_step.checklist.get("checklist", []):
            if item_dict.get("name") == check_item:
                item_dict["state"] = state

        self.save()

    def check(self):
        pass
