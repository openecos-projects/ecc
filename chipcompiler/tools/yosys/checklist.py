#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os

from chipcompiler.data import (
    Workspace, WorkspaceStep, Checklist, StepEnum, CheckState
)
from chipcompiler.utility import json_read

class YosysChecklist:
    CHECKLIST_ITEMS = {
        StepEnum.SYNTHESIS: [
            ("Input", "check RTL or filelist input"),
            ("Constraint", "check top module and frequency"),
            ("Library", "check synthesis liberty input"),
            ("Log", "check synthesis log"),
            ("Netlist", "check mapped gate netlist"),
            ("Metrics", "check synthesis cell statistics"),
        ],
    }

    def __init__(self,
                 workspace : Workspace,
                 workspace_step: WorkspaceStep,
                 init_checklist : bool = True):
        self.workspace = workspace
        self.workspace_step = workspace_step
        
        if init_checklist:
            self.build_checklist()

    def add_item(self,
                 checklist : Checklist,
                 step : str,
                 type : str,
                 item : str,
                 state : str,
                 info : str = ""):
        checklist.add(step=step,
                      type=type,
                      item=item,
                      state=state,
                      info=info)

        self.workspace.home.update_checklist(step=step,
                                             type=type,
                                             item=item,
                                             state=state,
                                             info=info)

    def add_items(self,
                  checklist : Checklist,
                  step : StepEnum):
        for type, item in self.CHECKLIST_ITEMS.get(step, []):
            self.add_item(checklist=checklist,
                          step=step.value,
                          type=type,
                          item=item,
                          state=CheckState.Unstart.value)

    def build_checklist(self) -> list:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        step = StepEnum(self.workspace_step.name)
        self.add_items(checklist=checklist,
                       step=step)
                
        self.workspace_step.checklist["checklist"] = checklist.data
    
    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        return checklist.save()
        
    def update_item(self, 
                    step : str, 
                    type : str,
                    item : str,
                    state : str | CheckState,
                    info : str = ""):
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        checklist.update(step=step, 
                         type=type, 
                         item=item, 
                         state=state,
                         info=info)

    def set_item_state(self,
                       step : str,
                       type : str,
                       item : str,
                       state : CheckState,
                       info : str = ""):
        self.update_item(step=step,
                         type=type,
                         item=item,
                         state=state,
                         info=info)
        self.workspace.home.update_checklist(step=step,
                                             type=type,
                                             item=item,
                                             state=state.value,
                                             info=info)

    def check(self):
        step = StepEnum(self.workspace_step.name)
        checker_class = {
            StepEnum.SYNTHESIS: YosysSynthesisChecklist,
        }.get(step)
        if checker_class is None:
            return True

        return checker_class(
            self.workspace,
            self.workspace_step,
            init_checklist=False,
        ).check()


class YosysSynthesisChecklist(YosysChecklist):
    def check_file(self,
                   path : str,
                   text_tokens : list | None = None) -> bool:
        if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False

        if not text_tokens:
            return True

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
        except OSError:
            return False

        return all(token in content for token in text_tokens)

    def to_float(self,
                 value,
                 default : float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def check(self) -> bool:
        step = StepEnum.SYNTHESIS.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        stat = json_read(self.workspace_step.feature.get("stat", ""))

        try:
            with open(self.workspace_step.log.get("file", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                log_text = file.read()
        except OSError:
            log_text = ""

        try:
            with open(self.workspace_step.output.get("verilog", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                netlist_text = file.read()
        except OSError:
            netlist_text = ""

        input_verilog = self.workspace_step.input.get("verilog", "")
        filelist = (
            self.workspace.design.input_filelist
            if self.workspace.design.input_filelist
            else self.workspace.parameters.data.get("File list", "")
        )
        top_module = self.workspace.design.top_module \
            or self.workspace.design.name
        frequency = self.to_float(
            self.workspace.parameters.data.get("Frequency max [MHz]"), 0.0)
        libs = getattr(self.workspace.pdk, "libs", []) or []
        modules = stat.get("modules", {})
        module_keys = {
            key.lstrip("\\")
            for key in modules
        }
        design_stat = stat.get("design", {})
        cell_number = self.to_float(
            metrics.get("Cell number", design_stat.get("num_cells")), 0.0)
        cell_area = self.to_float(
            metrics.get("Cell area", design_stat.get("area")), 0.0)
        log_lower = log_text.lower()
        log_success = (
            len(log_text) > 0
            and "end of script" in log_lower
            and not any(
                token in log_lower
                for token in [
                    "error:",
                    "fatal",
                    "syntax error",
                    "unmapped cell",
                    "blackbox",
                    "traceback",
                ]
            )
        )

        checks = [
            ("Input", "check RTL or filelist input",
             (input_verilog and os.path.isfile(input_verilog))
             or (filelist and os.path.isfile(filelist))),
            ("Constraint", "check top module and frequency",
             bool(top_module)
             and top_module in module_keys
             and frequency > 0),
            ("Library", "check synthesis liberty input",
             len(libs) > 0
             and all(os.path.isfile(path) for path in libs)
             and "-liberty" in stat.get("invocation", "")),
            ("Log", "check synthesis log", log_success),
            ("Netlist", "check mapped gate netlist",
             self.check_file(self.workspace_step.output.get("verilog", ""))
             and bool(top_module)
             and f"module {top_module}" in netlist_text),
            ("Metrics", "check synthesis cell statistics",
             cell_number > 0 and cell_area > 0),
        ]

        for type, item, success in checks:
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=CheckState.Passed if success else CheckState.Failed,
                info="" if success else f"{item} check failed",
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success for _, _, success in checks)
