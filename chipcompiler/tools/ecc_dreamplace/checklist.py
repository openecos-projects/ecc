#!/usr/bin/env python
import ast
import glob
import os
from pathlib import Path

from chipcompiler.data import (
    Checklist,
    CheckState,
    StepEnum,
    Workspace,
    WorkspaceStep,
)
from chipcompiler.tools.ecc.qor_metrics import QorMetrics
from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist
from chipcompiler.utility import json_read


class DreamplaceChecklist:
    CHECKLIST_ITEMS = {
        StepEnum.PLACEMENT: [
            ("Density", "check target density"),
            ("Density", "check placement overflow"),
            ("Wirelength", "check HPWL"),
            ("Legality", "check cell overlap"),
            ("Congestion", "check placement congestion"),
        ],
        StepEnum.LEGALIZATION: [
            ("Legality", "check cell overlap"),
            ("Legality", "check off-row placement"),
            ("Legality", "check site alignment"),
            ("Movement", "check legalization movement"),
            ("Fixed", "check fixed instances"),
        ],
    }

    def __init__(
        self, workspace: Workspace, workspace_step: WorkspaceStep, init_checklist: bool = True
    ):
        self.workspace = workspace
        self.workspace_step = workspace_step

        if init_checklist:
            self.build_checklist()

    def add_item(
        self, checklist: Checklist, step: str, type: str, item: str, state: str, info: str = ""
    ):
        checklist.add(step=step, type=type, item=item, state=state, info=info)
        self.workspace.home.update_checklist(
            step=step, type=type, item=item, state=state, info=info
        )

    def add_items(self, checklist: Checklist, step: StepEnum):
        for type, item in self.CHECKLIST_ITEMS.get(step, []):
            self.add_item(
                checklist=checklist,
                step=step.value,
                type=type,
                item=item,
                state=CheckState.Unstart.value,
            )

    def build_checklist(self) -> list:
        refresh_step_checklist(self.workspace, self.workspace_step)
        return self.workspace_step.checklist["checklist"]

    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        return checklist.save()

    def update_item(self, step: str, type: str, item: str, state: str | CheckState, info: str = ""):
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        checklist.update(step=step, type=type, item=item, state=state, info=info)

    def set_item_state(self, step: str, type: str, item: str, state: CheckState, info: str = ""):
        self.update_item(step=step, type=type, item=item, state=state, info=info)
        self.workspace.home.update_checklist(
            step=step, type=type, item=item, state=state.value, info=info
        )

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

    def check_file(self, path: str, text_tokens: list | None = None) -> bool:
        if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False

        if not text_tokens:
            return True

        try:
            with open(path, encoding="utf-8", errors="ignore") as file:
                content = file.read()
        except OSError:
            return False

        return all(token in content for token in text_tokens)

    def read_text(self, path: str) -> str:
        if not path or not os.path.isfile(path):
            return ""

        try:
            with open(path, encoding="utf-8", errors="ignore") as file:
                return file.read()
        except OSError:
            return ""

    def to_float(self, value, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def step_file_success(self) -> bool:
        return all(
            self.check_file(self.workspace_step.output.get(key, ""))
            for key in ("def", "verilog", "gds")
        )

    def qor_metrics(self) -> QorMetrics:
        return QorMetrics(self.workspace_step.analysis.get("metrics", ""))

    def feature_db(self) -> dict:
        return json_read(self.workspace_step.feature.get("db", ""))

    def feature_map(self) -> dict:
        return json_read(self.workspace_step.feature.get("map", ""))

    def dreamplace_config(self) -> dict:
        return json_read(self.workspace.config.get("dreamplace", ""))

    def log_text(self) -> str:
        return self.read_text(self.workspace_step.log.get("file", ""))

    def update_checks(self, checks: list) -> bool:
        step = self.workspace_step.name
        results = []
        for check in checks:
            if len(check) == 3:
                type, item, success = check
                info = f"{item} check failed"
                warning = False
            elif len(check) == 4:
                type, item, success, info = check
                warning = False
            else:
                type, item, success, info, warning = check

            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else info,
            )
            results.append(success or warning)

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(results)

    def final_ppa(self) -> dict:
        marker = "Final PPA:"
        data = {}
        for line in self.log_text().splitlines():
            if marker not in line:
                continue

            _, value = line.split(marker, 1)
            value = value.strip().replace("inf", "1e999")
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                continue
            if isinstance(parsed, dict):
                data = parsed

        return data

    def view_instances(self) -> dict:
        view_dir = self.workspace_step.output.get("view_json", "")
        return json_read(Path(view_dir) / "design" / "instances.json")

    def count_unplaced_instances(self) -> int | None:
        instances = self.view_instances().get("data", [])
        if not isinstance(instances, list):
            return None

        return sum(
            1 for inst in instances if inst.get("status", "") not in ("PLACED", "FIXED", "COVER")
        )

    def has_plot_files(self) -> bool:
        pattern = os.path.join(
            self.workspace_step.data.get(self.workspace_step.name, ""),
            self.workspace.design.name,
            "plot",
            "*.png",
        )
        return any(
            os.path.isfile(path) and os.path.getsize(path) > 0 for path in glob.glob(pattern)
        )


class DreamplacePlacementChecklist(DreamplaceChecklist):
    def cell_overlap_success(self) -> bool:
        text = self.log_text()
        unplaced = self.count_unplaced_instances()

        return (
            self.step_file_success()
            and "Start legalization" in text
            and "legalization takes" in text
            and (unplaced is None or unplaced == 0)
        )

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        metrics = self.qor_metrics()
        core_util, core_util_error = metrics.number("core_utilization")
        overflow_max, overflow_max_error = metrics.number("place_congestion_egr_overflow_max")
        overflow_total, overflow_total_error = metrics.number("place_congestion_egr_overflow_total")
        hpwl, hpwl_error = metrics.number("place_hpwl")
        lut_rudy, lut_rudy_error = metrics.number("place_lutrudy_utilization_max")
        rudy, rudy_error = metrics.number("place_rudy_utilization_max")
        config = self.dreamplace_config()
        target_density = self.to_float(config.get("target_density"))
        stop_overflow = self.to_float(config.get("stop_overflow"))
        density_success = (
            target_density is not None
            and target_density > 0
            and stop_overflow is not None
            and stop_overflow >= 0
            and core_util is not None
            and core_util > 0
        )
        overflow_success = (
            overflow_max is not None
            and overflow_total is not None
            and overflow_max == 0
            and overflow_total == 0
        )
        congestion_success = (
            overflow_max is not None
            and overflow_total is not None
            and lut_rudy is not None
            and rudy is not None
            and overflow_max >= 0
            and overflow_total >= 0
            and lut_rudy >= 0
            and rudy >= 0
            and self.has_plot_files()
        )
        checks = [
            (
                "Density",
                "check target density",
                density_success,
                core_util_error
                or (
                    f"target_density={target_density}, stop_overflow={stop_overflow}, "
                    f"core_utilization={core_util}"
                ),
            ),
            (
                "Density",
                "check placement overflow",
                overflow_success,
                overflow_max_error
                or overflow_total_error
                or (f"place EGR overflow max/total={overflow_max}/{overflow_total}"),
                True,
            ),
            (
                "Wirelength",
                "check HPWL",
                hpwl is not None and hpwl > 0,
                hpwl_error or f"place_hpwl must be positive, got {hpwl}",
                True,
            ),
            (
                "Legality",
                "check cell overlap",
                self.cell_overlap_success(),
                "legalization did not complete cleanly or unplaced cells remain",
            ),
            (
                "Congestion",
                "check placement congestion",
                congestion_success,
                overflow_max_error
                or overflow_total_error
                or lut_rudy_error
                or rudy_error
                or "Placement congestion metrics or plot files are missing",
                True,
            ),
        ]

        return self.update_checks(checks)


class DreamplaceLegalizationChecklist(DreamplaceChecklist):
    def log_legalization_success(self) -> bool:
        text = self.log_text()
        return (
            "Start legalization" in text
            and "legalization takes" in text
            and "num_unplaced_cells = 0" in text
        )

    def cell_overlap_success(self) -> bool:
        text = self.log_text()
        unplaced = self.count_unplaced_instances()

        return (
            self.step_file_success()
            and "Legality check takes" in text
            and (unplaced is None or unplaced == 0)
        )

    def site_alignment_success(self) -> bool:
        db = self.feature_db()
        layout = db.get("Design Layout", {})
        core_usage = self.to_float(layout.get("core_usage"))
        instance_count = self.to_float(db.get("Design Statis", {}).get("num_instances"))

        return (
            core_usage is not None
            and core_usage > 0
            and instance_count is not None
            and instance_count > 0
            and self.log_legalization_success()
        )

    def movement_success(self) -> bool:
        ppa = self.final_ppa()
        hpwl = self.to_float(ppa.get("hpwl"))
        text = self.log_text()

        return (
            hpwl is not None
            and hpwl > 0
            and ("average displace" in text or "placement takes" in text)
        )

    def fixed_success(self) -> bool:
        text = self.log_text()
        return (
            self.step_file_success()
            and "Macro legalization" in text
            and "WriteBack placement finished" in text
        )

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        checks = [
            (
                "Legality",
                "check cell overlap",
                self.cell_overlap_success(),
                "legality check did not complete cleanly or unplaced cells remain",
            ),
            (
                "Legality",
                "check off-row placement",
                self.log_legalization_success(),
                "legalization log does not report zero unplaced cells",
            ),
            (
                "Legality",
                "check site alignment",
                self.site_alignment_success(),
                "site alignment proxy metrics are missing or invalid",
            ),
            (
                "Movement",
                "check legalization movement",
                self.movement_success(),
                "legalization movement/HPWL metrics are missing",
                True,
            ),
            (
                "Fixed",
                "check fixed instances",
                self.fixed_success(),
                "fixed instance writeback or macro legalization log marker is missing",
            ),
        ]

        return self.update_checks(checks)
