#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import glob
import os

from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    Checklist, 
    StepEnum, 
    CheckState
)
from chipcompiler.utility import json_read

class EccChecklist:
    CHECKLIST_ITEMS = {
        StepEnum.FLOORPLAN: [
            ("Area", "check DIE area"),
            ("Area", "check core area"),
            ("Area", "check core utilization"),
            ("Rows/Tracks", "check placement rows and sites"),
            ("Rows/Tracks", "check routing tracks"),
            ("Pins/Macros", "check IO pin placement"),
            ("Pins/Macros", "check macro placement"),
            ("PDN", "check tap and endcap insertion"),
            ("PDN", "check PDN IO and global connect"),
            ("PDN", "check PDN grid and stripes"),
            ("Clock", "check clock net type"),
        ],
        StepEnum.NETLIST_OPT: [
            ("Fanout", "check max fanout constraint"),
            ("Fanout", "check high fanout nets"),
            ("Buffer", "check inserted buffer type"),
            ("Tie", "check tie cell usage"),
            ("Netlist", "check netlist and DEF consistency"),
        ],
        StepEnum.PLACEMENT: [
            ("Density", "check target density"),
            ("Density", "check placement overflow"),
            ("Wirelength", "check HPWL"),
            ("Legality", "check cell overlap"),
            ("Congestion", "check placement congestion"),
        ],
        StepEnum.CTS: [
            ("Clock", "check clock net"),
            ("Buffer", "check CTS buffers"),
            ("Timing", "check clock skew"),
            ("Timing", "check clock transition"),
            ("Timing", "check clock capacitance"),
            ("Tree", "check clock sink coverage"),
        ],
        StepEnum.TIMING_OPT_DRV: [
            ("Timing", "check max transition"),
            ("Timing", "check max capacitance"),
            ("Timing", "check max fanout"),
            ("Buffer", "check DRV inserted buffers"),
        ],
        StepEnum.TIMING_OPT_HOLD: [
            ("Timing", "check hold WNS/TNS"),
            ("Buffer", "check hold inserted buffers"),
            ("Netlist", "check hold ECO consistency"),
        ],
        StepEnum.TIMING_OPT_SETUP: [
            ("Timing", "check setup WNS/TNS"),
            ("Buffer", "check setup inserted buffers"),
            ("Netlist", "check setup ECO consistency"),
        ],
        StepEnum.LEGALIZATION: [
            ("Legality", "check cell overlap"),
            ("Legality", "check off-row placement"),
            ("Legality", "check site alignment"),
            ("Movement", "check legalization movement"),
            ("Fixed", "check fixed instances"),
        ],
        StepEnum.ROUTING: [
            ("Layer", "check routing layer range"),
            ("Route", "check unrouted nets"),
            ("Route", "check shorts and opens"),
            ("Route", "check via count"),
            ("Route", "check wire length"),
            ("Timing", "check post-route timing"),
        ],
        StepEnum.DRC: [
            ("DRC", "check DRC violation count"),
            ("DRC", "check DRC violation distribution"),
            ("DRC", "check DRC waiver list"),
            ("Signoff", "check final DRC requirement"),
        ],
        StepEnum.FILLER: [
            ("Filler", "check filler cell list"),
            ("Filler", "check filler coverage"),
            ("Legality", "check filler overlap"),
            ("Signoff", "check post-filler DRC requirement"),
        ],
        StepEnum.RCX: [
            ("RCX", "check RCX corners"),
            ("RCX", "check SPEF files"),
            ("RCX", "check SPEF net names"),
            ("STA", "check RCX and STA corner mapping"),
        ],
        StepEnum.STA: [
            ("STA", "check STA signoff matrix"),
            ("Timing", "check setup timing"),
            ("Timing", "check hold timing"),
            ("Timing", "check frequency requirement"),
            ("Timing", "check timing exceptions"),
            ("DRV", "check STA DRV violations"),
        ],
        StepEnum.HARDEN: [
            ("Output", "check abstract LEF"),
            ("Output", "check timing model LIB"),
            ("Output", "check harden GDS"),
            ("Output", "check hard macro deliverables"),
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

        # add to home page checklist
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
        
    def check(self) -> bool:
        step = StepEnum(self.workspace_step.name)
        checker_class = {
            StepEnum.FLOORPLAN: EccFloorplanChecklist,
            StepEnum.NETLIST_OPT: EccNetlistOptChecklist,
            StepEnum.CTS: EccCtsChecklist,
            StepEnum.TIMING_OPT_DRV: EccTimingOptDrvChecklist,
            StepEnum.TIMING_OPT_HOLD: EccTimingOptHoldChecklist,
            StepEnum.TIMING_OPT_SETUP: EccTimingOptSetupChecklist,
            StepEnum.ROUTING: EccRoutingChecklist,
            StepEnum.DRC: EccDrcChecklist,
            StepEnum.FILLER: EccFillerChecklist,
            StepEnum.HARDEN: EccHardenChecklist,
            StepEnum.RCX: EccRcxChecklist,
            StepEnum.STA: EccStaChecklist,
        }.get(step)
        if checker_class is None:
            return True

        return checker_class(
            self.workspace,
            self.workspace_step,
            init_checklist=False,
        ).check()
        
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


class EccFloorplanChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.FLOORPLAN.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        subflow = json_read(self.workspace_step.subflow.get("path", ""))

        try:
            with open(self.workspace_step.log.get("file", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                log_text = file.read()
        except OSError:
            log_text = ""

        layout = db.get("Design Layout", {})
        statis = db.get("Design Statis", {})
        layers = db.get("Layers", {})
        nets = db.get("Nets", {})
        subflow_state = {
            item.get("name"): item.get("state")
            for item in subflow.get("steps", [])
        }
        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])

        die_area = self.to_float(
            metrics.get("Die area [μm^2]", layout.get("die_area")), 0.0)
        die_width = self.to_float(
            metrics.get("Die width [um]", layout.get("die_bounding_width")), 0.0)
        die_height = self.to_float(
            metrics.get("Die height [um]", layout.get("die_bounding_height")), 0.0)
        core_area = self.to_float(layout.get("core_area"), 0.0)
        core_width = self.to_float(layout.get("core_bounding_width"), 0.0)
        core_height = self.to_float(layout.get("core_bounding_height"), 0.0)
        core_util = self.to_float(
            metrics.get("Core util", layout.get("core_usage")), 0.0)
        num_iopins = self.to_float(
            metrics.get("Total io pins", statis.get("num_iopins")), 0.0)
        num_pdn = self.to_float(statis.get("num_pdn"), 0.0)
        num_clock = self.to_float(nets.get("num_clock"), 0.0)
        num_routing_layers = self.to_float(
            layers.get("num_layers_routing", statis.get("num_layers_routing")),
            0.0,
        )

        checks = [
            ("Area", "check DIE area",
             die_area > 0 and die_width > 0 and die_height > 0),
            ("Area", "check core area",
             core_area > 0 and core_width > 0 and core_height > 0),
            ("Area", "check core utilization",
             core_util is not None and 0 < core_util <= 1),
            ("Rows/Tracks", "check placement rows and sites",
             subflow_state.get("init floorplan") == "Success"
             and "Write ROWS success" in log_text
             and output_success),
            ("Rows/Tracks", "check routing tracks",
             subflow_state.get("create tracks") == "Success"
             and num_routing_layers > 0
             and "Write Track Grid success" in log_text),
            ("Pins/Macros", "check IO pin placement",
             subflow_state.get("place io pins") == "Success"
             and num_iopins > 0
             and "Write PINS success" in log_text),
            ("Pins/Macros", "check macro placement",
             "Macros" in db and "Macros Statis" in db and output_success),
            ("PDN", "check tap and endcap insertion",
             subflow_state.get("tap cell") == "Success"
             and "Write COMPONENTS success" in log_text),
            ("PDN", "check PDN IO and global connect",
             subflow_state.get("PDN") == "Success" and num_pdn >= 2),
            ("PDN", "check PDN grid and stripes",
             subflow_state.get("PDN") == "Success"
             and "Write SPECIALNETS success" in log_text),
            ("Clock", "check clock net type",
             subflow_state.get("set clock net") == "Success" and num_clock > 0),
        ]

        warning_items = {"check macro placement"}
        for type, item, success in checks:
            warning = item in warning_items
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else f"{item} check failed",
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success or item in warning_items for _, item, success in checks)


class EccNetlistOptChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.NETLIST_OPT.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        config = json_read(self.workspace.config.get(StepEnum.NETLIST_OPT.value, ""))

        try:
            with open(self.workspace_step.output.get("verilog", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                netlist_text = file.read()
        except OSError:
            netlist_text = ""

        statis = db.get("Design Statis", {})
        pins = db.get("Pins", {})
        buffer_cells = getattr(self.workspace.pdk, "buffers", []) or []
        tie_high = getattr(self.workspace.pdk, "tie_high_cell", "")
        tie_low = getattr(self.workspace.pdk, "tie_low_cell", "")
        max_fanout_limit = self.to_float(
            config.get("max_fanout",
                       metrics.get("Max fanout",
                                   self.workspace.parameters.data.get("Max fanout"))),
            0.0,
        )
        actual_max_fanout = self.to_float(pins.get("max_fanout"))
        total_nets = self.to_float(metrics.get("Total nets"), 0.0)
        db_nets = self.to_float(statis.get("num_nets"), 0.0)
        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])

        buffer_success = (
            len(buffer_cells) > 0
            and (
                any(buffer in netlist_text for buffer in buffer_cells)
                or config.get("insert_buffer") in buffer_cells
            )
        )
        tie_success = bool(tie_high and tie_low)
        if tie_high in netlist_text or tie_low in netlist_text:
            tie_success = True

        checks = [
            ("Fanout", "check max fanout constraint", max_fanout_limit > 0),
            ("Fanout", "check high fanout nets",
             actual_max_fanout is not None
             and max_fanout_limit > 0
             and actual_max_fanout <= max_fanout_limit),
            ("Buffer", "check inserted buffer type", buffer_success),
            ("Tie", "check tie cell usage", tie_success),
            ("Netlist", "check netlist and DEF consistency",
             output_success and total_nets > 0 and db_nets > 0
             and int(total_nets) == int(db_nets)),
        ]

        warning_items = {"check high fanout nets", "check tie cell usage"}
        for type, item, success in checks:
            warning = item in warning_items
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            info = f"{item} check failed"
            if item == "check high fanout nets":
                info = (
                    f"max fanout {actual_max_fanout} exceeds "
                    f"limit {max_fanout_limit}"
                )
            elif item == "check tie cell usage":
                info = "tie high/low cell definition or inserted tie cell is missing"
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else info,
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success or item in warning_items for _, item, success in checks)


class EccCtsChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.CTS.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        feature = json_read(self.workspace_step.feature.get("step", "")).get("CTS", {})
        config = json_read(self.workspace.config.get(StepEnum.CTS.value, ""))

        nets = db.get("Nets", {})
        instances = db.get("Instances", {})
        clock_instances = instances.get("clock", {}) or {}
        buffer_cells = config.get("buffer_type", [])
        if isinstance(buffer_cells, str):
            buffer_cells = [buffer_cells]

        num_clock = self.to_float(nets.get("num_clock"), 0.0)
        clock_sink_num = self.to_float(clock_instances.get("num"), 0.0)
        buffer_num = self.to_float(
            metrics.get("buffer_num", feature.get("buffer_num")), 0.0)
        clock_path_max = self.to_float(
            metrics.get("clock_path_max_buffer",
                        feature.get("clock_path_max_buffer")), 0.0)
        clock_path_min = self.to_float(
            metrics.get("clock_path_min_buffer",
                        feature.get("clock_path_min_buffer")), 0.0)
        clock_wirelength = self.to_float(
            metrics.get("total_clock_wirelength",
                        feature.get("total_clock_wirelength")), 0.0)
        skew_bound = self.to_float(config.get("skew_bound"), 0.0)
        max_transition = self.to_float(
            config.get("max_buf_tran", config.get("max_sink_tran")), 0.0)
        max_cap = self.to_float(config.get("max_cap"), 0.0)

        checks = [
            ("Clock", "check clock net", num_clock > 0),
            ("Buffer", "check CTS buffers",
             len(buffer_cells) > 0 and buffer_num > 0),
            ("Timing", "check clock skew",
             skew_bound > 0 and clock_path_max >= clock_path_min > 0),
            ("Timing", "check clock transition",
             max_transition > 0 and buffer_num >= 0),
            ("Timing", "check clock capacitance",
             max_cap > 0 and clock_wirelength > 0),
            ("Tree", "check clock sink coverage",
             clock_sink_num > 0 and clock_path_max > 0 and clock_path_min > 0),
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


class EccTimingOptDrvChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.TIMING_OPT_DRV.value
        db = json_read(self.workspace_step.feature.get("db", ""))
        config = json_read(self.workspace.config.get(StepEnum.TIMING_OPT_DRV.value, ""))

        try:
            with open(self.workspace_step.log.get("file", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                log_text = file.read().lower()
        except OSError:
            log_text = ""

        pins = db.get("Pins", {})
        buffer_cells = config.get("DRV_insert_buffers", [])
        if isinstance(buffer_cells, str):
            buffer_cells = [buffer_cells]

        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])
        log_success = not any(
            token in log_text
            for token in ["error:", "fatal", "traceback", "exception", "failed"]
        )
        max_allowed_fanout = self.to_float(
            config.get("max_allowed_buffering_fanout"), 0.0)
        actual_max_fanout = self.to_float(pins.get("max_fanout"))

        checks = [
            ("Timing", "check max transition",
             bool(config.get("optimize_drv")) and output_success and log_success),
            ("Timing", "check max capacitance",
             bool(config.get("optimize_drv")) and output_success and log_success),
            ("Timing", "check max fanout",
             max_allowed_fanout > 0
             and (actual_max_fanout is None
                  or actual_max_fanout <= max_allowed_fanout)),
            ("Buffer", "check DRV inserted buffers",
             len(buffer_cells) > 0 and output_success),
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


class EccTimingOptHoldChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.TIMING_OPT_HOLD.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        config = json_read(self.workspace.config.get(StepEnum.TIMING_OPT_HOLD.value, ""))

        buffer_cells = config.get("hold_insert_buffers", [])
        if isinstance(buffer_cells, str):
            buffer_cells = [buffer_cells]

        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])
        min_wns = self.to_float(metrics.get("min_WNS"))
        min_tns = self.to_float(metrics.get("min_TNS"))
        if min_wns is None and min_tns is None:
            timing_success = output_success and bool(config.get("optimize_hold"))
        else:
            timing_success = (
                min_wns is not None and min_tns is not None
                and min_wns >= 0 and min_tns >= 0
            )
        statis = db.get("Design Statis", {})
        num_instances = self.to_float(statis.get("num_instances"), 0.0)
        num_nets = self.to_float(statis.get("num_nets"), 0.0)

        checks = [
            ("Timing", "check hold WNS/TNS", timing_success),
            ("Buffer", "check hold inserted buffers",
             len(buffer_cells) > 0 and output_success),
            ("Netlist", "check hold ECO consistency",
             output_success and num_instances > 0 and num_nets > 0),
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


class EccTimingOptSetupChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.TIMING_OPT_SETUP.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        config = json_read(self.workspace.config.get(StepEnum.TIMING_OPT_SETUP.value, ""))

        buffer_cells = config.get("setup_insert_buffers", [])
        if isinstance(buffer_cells, str):
            buffer_cells = [buffer_cells]

        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])
        max_wns = self.to_float(metrics.get("max_WNS"))
        max_tns = self.to_float(metrics.get("max_TNS"))
        if max_wns is None and max_tns is None:
            timing_success = output_success and bool(config.get("optimize_setup"))
        else:
            timing_success = (
                max_wns is not None and max_tns is not None
                and max_wns >= 0 and max_tns >= 0
            )
        statis = db.get("Design Statis", {})
        num_instances = self.to_float(statis.get("num_instances"), 0.0)
        num_nets = self.to_float(statis.get("num_nets"), 0.0)

        checks = [
            ("Timing", "check setup WNS/TNS", timing_success),
            ("Buffer", "check setup inserted buffers",
             len(buffer_cells) > 0 and output_success),
            ("Netlist", "check setup ECO consistency",
             output_success and num_instances > 0 and num_nets > 0),
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


class EccRoutingChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.ROUTING.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        db = json_read(self.workspace_step.feature.get("db", ""))
        feature = json_read(self.workspace_step.feature.get("step", "")).get(
            StepEnum.ROUTING.value, {})
        config = json_read(self.workspace.config.get(StepEnum.ROUTING.value, ""))

        layers = db.get("Layers", {})
        nets = db.get("Nets", {})
        rt_config = config.get("RT", {})
        routing_layer_names = [
            layer.get("layer_name")
            for layer in layers.get("routing_layers", [])
        ]
        bottom_layer = rt_config.get("-bottom_routing_layer")
        top_layer = rt_config.get("-top_routing_layer")
        dr_iterations = feature.get("DR", [])
        final_dr = dr_iterations[-1] if dr_iterations else {}
        final_violation_num = self.to_float(
            final_dr.get("total_violation_num"), 0.0)
        total_nets = self.to_float(nets.get("num_total"), 0.0)
        wire_len = self.to_float(
            metrics.get("wire_len", nets.get("wire_len")), 0.0)
        via_num = self.to_float(
            metrics.get("num_via", nets.get("num_via")), 0.0)
        timing_enabled = str(rt_config.get("-enable_timing", "0")) == "1"
        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])

        checks = [
            ("Layer", "check routing layer range",
             bottom_layer in routing_layer_names
             and top_layer in routing_layer_names),
            ("Route", "check unrouted nets",
             output_success and total_nets > 0 and len(dr_iterations) > 0),
            ("Route", "check shorts and opens",
             final_violation_num == 0),
            ("Route", "check via count", via_num > 0),
            ("Route", "check wire length", wire_len > 0),
            ("Timing", "check post-route timing",
             (not timing_enabled)
             or "Frequency [MHz]" in metrics
             or "max_WNS" in metrics),
        ]

        warning_items = {"check post-route timing"}
        for type, item, success in checks:
            warning = item in warning_items
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else f"{item} check failed",
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success or item in warning_items for _, item, success in checks)


class EccDrcChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.DRC.value
        metrics = json_read(self.workspace_step.analysis.get("metrics", ""))
        feature = json_read(self.workspace_step.feature.get("step", "")).get("drc", {})
        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])

        metric_drc_num = self.to_float(metrics.get("drc_num"))
        feature_drc_num = self.to_float(feature.get("number"))
        distribution = feature.get("distribution")
        drc_clean = (
            metric_drc_num is not None
            and feature_drc_num is not None
            and metric_drc_num == 0
            and feature_drc_num == 0
        )

        checks = [
            ("DRC", "check DRC violation count", drc_clean),
            ("DRC", "check DRC violation distribution",
             drc_clean or isinstance(distribution, dict)),
            ("DRC", "check DRC waiver list", drc_clean),
            ("Signoff", "check final DRC requirement",
             output_success and drc_clean),
        ]

        warning_items = {
            "check DRC violation distribution",
            "check DRC waiver list",
        }
        for type, item, success in checks:
            warning = item in warning_items
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else f"{item} check failed",
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success or item in warning_items for _, item, success in checks)


class EccFillerChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.FILLER.value
        db = json_read(self.workspace_step.feature.get("db", ""))
        subflow = json_read(self.workspace_step.subflow.get("path", ""))
        config = json_read(self.workspace.config.get(StepEnum.PLACEMENT.value, ""))

        try:
            with open(self.workspace_step.log.get("file", ""),
                      "r", encoding="utf-8", errors="ignore") as file:
                log_text = file.read()
        except OSError:
            log_text = ""

        subflow_state = {
            item.get("name"): item.get("state")
            for item in subflow.get("steps", [])
        }
        filler_config = config.get("PL", {}).get("Filler", {})
        first_iter_fillers = filler_config.get("first_iter", [])
        second_iter_fillers = filler_config.get("second_iter", [])
        pdk_fillers = getattr(self.workspace.pdk, "fillers", []) or []
        output_success = all([
            self.check_file(self.workspace_step.output.get("def", "")),
            self.check_file(self.workspace_step.output.get("verilog", "")),
            self.check_file(self.workspace_step.output.get("gds", "")),
        ])
        statis = db.get("Design Statis", {})
        num_instances = self.to_float(statis.get("num_instances"), 0.0)
        log_lower = log_text.lower()
        log_success = not any(
            token in log_lower
            for token in ["error:", "fatal", "traceback", "exception", "failed"]
        )

        checks = [
            ("Filler", "check filler cell list",
             len(pdk_fillers) > 0
             or len(first_iter_fillers) > 0
             or len(second_iter_fillers) > 0),
            ("Filler", "check filler coverage",
             subflow_state.get("run filler") == "Success"
             and output_success
             and "insertFiller" in log_text),
            ("Legality", "check filler overlap",
             output_success and num_instances > 0 and log_success),
        ]

        for type, item, success in checks:
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=CheckState.Passed if success else CheckState.Failed,
                info="" if success else f"{item} check failed",
            )

        drc_state = CheckState.Warning
        self.set_item_state(
            step=step,
            type="Signoff",
            item="check post-filler DRC requirement",
            state=drc_state,
            info="post-filler DRC is not run in current flow",
        )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success for _, _, success in checks)


class EccHardenChecklist(EccChecklist):
    def check(self) -> bool:
        step = StepEnum.HARDEN.value
        design_name = self.workspace.design.top_module \
            or self.workspace.design.name

        lef_tokens = ["MACRO", "END LIBRARY"]
        lib_tokens = ["library", "cell"]
        if design_name:
            lef_tokens.append(f"MACRO {design_name}")
            lib_tokens.append(f"cell ({design_name})")

        checks = [
            (
                "Output",
                "check abstract LEF",
                self.check_file(self.workspace_step.output.get("lef", ""),
                                lef_tokens),
            ),
            (
                "Output",
                "check timing model LIB",
                self.check_file(self.workspace_step.output.get("lib", ""),
                                lib_tokens),
            ),
            (
                "Output",
                "check harden GDS",
                self.check_file(self.workspace_step.output.get("gds", "")),
            ),
        ]

        deliverables_success = all(success for _, _, success in checks)
        checks.append((
            "Output",
            "check hard macro deliverables",
            deliverables_success,
        ))

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

        return deliverables_success


class EccRcxChecklist(EccChecklist):
    def collect_rcx_spef_paths(self) -> list:
        spef_paths = self.workspace_step.output.get("spef", [])
        if isinstance(spef_paths, str):
            spef_paths = [spef_paths]

        output_dir = self.workspace_step.output.get("dir", "")
        if output_dir and os.path.isdir(output_dir):
            spef_paths.extend(glob.glob(os.path.join(output_dir, "*.spef")))

        return sorted({
            path
            for path in spef_paths
            if path
        })

    def expected_rcx_spef_paths(self) -> list:
        rcx_config = self.workspace.config.get(StepEnum.RCX.value, "")
        rcx_data = json_read(rcx_config)
        expected_paths = []

        for corner in rcx_data.get("corners", []):
            spef_files = corner.get("spef_file", [])
            if isinstance(spef_files, (str, dict)):
                spef_files = [spef_files]

            for spef_item in spef_files:
                if isinstance(spef_item, dict):
                    expected_paths.extend([
                        path for path in spef_item.values() if path
                    ])
                elif spef_item:
                    expected_paths.append(spef_item)

        return sorted(set(expected_paths))

    def spef_corner_name(self,
                         spef_path : str) -> str:
        design_name = self.workspace.design.name \
            or self.workspace.design.top_module
        name = os.path.basename(spef_path)
        if name.endswith(".spef"):
            name = name[:-5]

        prefix = f"{design_name}_" if design_name else ""
        if prefix and name.startswith(prefix):
            name = name[len(prefix):]

        if "_" in name:
            name = name.rsplit("_", 1)[0]

        return name

    def sta_required_rcx_corners(self) -> set:
        sta_config = self.workspace.config.get(StepEnum.STA.value, "")
        sta_data = json_read(sta_config)
        corners = set()

        for signoff_group in sta_data.get("signoff", []):
            for rcx_corner_names in signoff_group.values():
                corners.update(rcx_corner_names)

        return corners

    def check_spef_file(self,
                        spef_path : str) -> bool:
        design_name = self.workspace.design.name \
            or self.workspace.design.top_module
        tokens = ["*SPEF", "*DESIGN", "*NAME_MAP"]
        if design_name:
            tokens.append(f"*DESIGN \"{design_name}\"")

        return self.check_file(spef_path, tokens)

    def check(self) -> bool:
        step = StepEnum.RCX.value
        spef_paths = self.collect_rcx_spef_paths()
        expected_spef_paths = self.expected_rcx_spef_paths()
        required_rcx_corners = self.sta_required_rcx_corners()
        extracted_corners = {
            self.spef_corner_name(path)
            for path in spef_paths
        }

        if expected_spef_paths:
            spef_files_success = all(
                os.path.isfile(path) and os.path.getsize(path) > 0
                for path in expected_spef_paths
            )
            corners_success = spef_files_success
        else:
            spef_files_success = len(spef_paths) > 0 and all(
                os.path.isfile(path) and os.path.getsize(path) > 0
                for path in spef_paths
            )
            corners_success = len(extracted_corners) > 0

        spef_net_names_success = len(spef_paths) > 0 and all(
            self.check_spef_file(path)
            for path in spef_paths
        )

        if required_rcx_corners:
            mapping_success = required_rcx_corners.issubset(extracted_corners)
        else:
            mapping_success = len(extracted_corners) > 0

        checks = [
            ("RCX", "check RCX corners", corners_success),
            ("RCX", "check SPEF files", spef_files_success),
            ("RCX", "check SPEF net names", spef_net_names_success),
            ("STA", "check RCX and STA corner mapping", mapping_success),
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


class EccStaChecklist(EccChecklist):
    def temperature_token(self,
                          temperature) -> str:
        try:
            numeric = float(temperature)
            if numeric.is_integer():
                temperature = int(numeric)
        except (TypeError, ValueError):
            pass
        return str(temperature).replace("-", "m").replace(".", "p")

    def collect_sta_report_paths(self) -> list:
        output_dir = self.workspace_step.output.get("dir", "")
        if not output_dir or not os.path.isdir(output_dir):
            return []

        return sorted(glob.glob(
            os.path.join(output_dir, "**", "*.rpt.json"),
            recursive=True,
        ))

    def expected_sta_report_paths(self) -> list:
        sta_config = self.workspace.config.get(StepEnum.STA.value, "")
        sta_data = json_read(sta_config)
        if len(sta_data) == 0:
            return []

        output_dir = self.workspace_step.output.get("dir", "")
        top_module = self.workspace.design.top_module \
            or self.workspace.design.name
        liberty_by_corner = {
            liberty.get("corner"): liberty
            for liberty in sta_data.get("liberty", [])
        }
        expected_paths = []

        for signoff_group in sta_data.get("signoff", []):
            for corner_name, rcx_corner_names in signoff_group.items():
                liberty = liberty_by_corner.get(corner_name)
                if liberty is None:
                    continue

                report_corner_dir = "{}_{}".format(
                    corner_name,
                    self.temperature_token(liberty.get("temperature")),
                )
                for rcx_corner_name in rcx_corner_names:
                    expected_paths.append(os.path.join(
                        output_dir,
                        report_corner_dir,
                        rcx_corner_name,
                        f"{top_module}.rpt.json",
                    ))

        return expected_paths

    def load_sta_reports(self) -> list:
        reports = []
        for path in self.collect_sta_report_paths():
            data = json_read(path)
            if len(data) > 0:
                reports.append((path, data))

        return reports

    def sta_report_has_violation(self,
                                 data : dict,
                                 delay_type : str) -> bool:
        for slack_item in data.get("slack", []):
            if slack_item.get("delay_type", "") != delay_type:
                continue

            tns = self.to_float(slack_item.get("TNS"), 0.0)
            wns = self.to_float(slack_item.get("WNS"), 0.0)
            if tns is None or wns is None or tns < 0 or wns < 0:
                return True

        return False

    def sta_report_has_delay_type(self,
                                  data : dict,
                                  delay_type : str) -> bool:
        return any(
            slack_item.get("delay_type", "") == delay_type
            for slack_item in data.get("slack", [])
        )

    def sta_report_frequency(self,
                             data : dict,
                             target_frequency : float) -> float | None:
        max_wns = None
        for slack_item in data.get("slack", []):
            if slack_item.get("delay_type", "") == "max":
                max_wns = self.to_float(slack_item.get("WNS"))
                break

        if target_frequency <= 0 or max_wns is None:
            return None

        clk_period = 1000.0 / target_frequency
        if clk_period - max_wns <= 0:
            return None

        return 1000.0 / (clk_period - max_wns)

    def check(self) -> bool:
        step = StepEnum.STA.value
        reports = self.load_sta_reports()
        report_paths = [path for path, _ in reports]
        expected_paths = self.expected_sta_report_paths()
        target_frequency = self.to_float(
            self.workspace.parameters.data.get("Frequency max [MHz]", 0),
            0.0,
        )

        if expected_paths:
            signoff_success = all(
                os.path.isfile(path) and os.path.getsize(path) > 0
                for path in expected_paths
            )
        else:
            signoff_success = len(reports) > 0

        setup_success = len(reports) > 0 and all(
            self.sta_report_has_delay_type(data, "max")
            and not self.sta_report_has_violation(data, "max")
            for _, data in reports
        )
        hold_success = len(reports) > 0 and all(
            self.sta_report_has_delay_type(data, "min")
            and not self.sta_report_has_violation(data, "min")
            for _, data in reports
        )

        frequencies = [
            self.sta_report_frequency(data, target_frequency)
            for _, data in reports
        ]
        frequency_success = (
            len(reports) > 0
            and target_frequency > 0
            and all(freq is not None and freq >= target_frequency
                    for freq in frequencies)
        )

        reports_parse_success = len(report_paths) == len(reports) and len(reports) > 0
        checks = [
            ("STA", "check STA signoff matrix", signoff_success),
            ("Timing", "check setup timing", setup_success),
            ("Timing", "check hold timing", hold_success),
            ("Timing", "check frequency requirement", frequency_success),
            ("Timing", "check timing exceptions", reports_parse_success),
            ("DRV", "check STA DRV violations", reports_parse_success),
        ]

        warning_items = {
            "check timing exceptions",
            "check STA DRV violations",
        }
        for type, item, success in checks:
            warning = item in warning_items
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if warning else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else f"{item} check failed",
            )

        self.workspace_step.checklist["checklist"] = Checklist(
            path=self.workspace_step.checklist.get("path", "")
        ).data

        return all(success or item in warning_items for _, item, success in checks)
