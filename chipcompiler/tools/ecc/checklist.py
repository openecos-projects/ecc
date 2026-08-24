#!/usr/bin/env python
import glob
import os
from pathlib import Path

from chipcompiler.data import Checklist, CheckState, EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc.qor_metrics import QorMetrics
from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist
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
            ("STA", "check STA QoR summary data"),
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

    def __init__(
        self, workspace: Workspace, workspace_step: EccStep, *, init_checklist: bool = True
    ):
        self.workspace = workspace
        self.workspace_step = workspace_step

        if init_checklist:
            self.build_checklist()

    def add_item(
        self, checklist: Checklist, step: str, type: str, item: str, state: str, info: str = ""
    ):
        checklist.add(step=step, type=type, item=item, state=state, info=info)

        # add to home page checklist
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

    def set_item_state(self, step: str, type: str, item: str, state: CheckState, info: str = ""):
        self.update_item(step=step, type=type, item=item, state=state, info=info)
        self.workspace.home.update_checklist(
            step=step, type=type, item=item, state=state.value, info=info
        )

    def build_checklist(self) -> list:
        refresh_step_checklist(self.workspace, self.workspace_step)
        return self.workspace_step.checklist.checklist

    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.path or "")
        return checklist.save()

    def update_item(self, step: str, type: str, item: str, state: str | CheckState, info: str = ""):
        checklist = Checklist(path=self.workspace_step.checklist.path or "")
        checklist.update(step=step, type=type, item=item, state=state, info=info)

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

    def check_file(self, path: str | Path, text_tokens: list | None = None) -> bool:
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

    def to_float(self, value, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def qor_metrics(self) -> QorMetrics:
        return QorMetrics(self.workspace_step.analysis.metrics or "")

    def apply_checks(
        self, step: str, checks: list[tuple[str, str, bool, str]], warnings: set[str] | None = None
    ) -> bool:
        warnings = warnings or set()
        for type, item, success, info in checks:
            state = CheckState.Passed
            if not success:
                state = CheckState.Warning if item in warnings else CheckState.Failed
            self.set_item_state(
                step=step,
                type=type,
                item=item,
                state=state,
                info="" if success else info,
            )

        self.workspace_step.checklist.checklist = Checklist(
            path=self.workspace_step.checklist.path or ""
        ).data
        return all(success or item in warnings for _, item, success, _ in checks)


class EccFloorplanChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.FLOORPLAN.value
        metrics = self.qor_metrics()
        db = json_read(self.workspace_step.feature.db or "")
        subflow = json_read(self.workspace_step.subflow.path or "")

        try:
            with open(
                self.workspace_step.log.file or "",
                encoding="utf-8",
                errors="ignore",
            ) as file:
                log_text = file.read()
        except OSError:
            log_text = ""

        layout = db.get("Design Layout", {})
        statis = db.get("Design Statis", {})
        layers = db.get("Layers", {})
        nets = db.get("Nets", {})
        subflow_state = {item.get("name"): item.get("state") for item in subflow.get("steps", [])}
        output_success = all(
            [
                self.check_file(self.workspace_step.output.def_ or ""),
                self.check_file(self.workspace_step.output.verilog or ""),
                self.check_file(self.workspace_step.output.gds or ""),
            ]
        )

        die_area, die_area_error = metrics.number("die_area")
        die_width, die_width_error = metrics.number("die_width")
        die_height, die_height_error = metrics.number("die_height")
        core_area_metric, core_area_error = metrics.number("core_area")
        core_util, core_util_error = metrics.number("core_utilization")
        num_iopins, io_pin_error = metrics.number("io_pin_count")
        core_area = self.to_float(layout.get("core_area"), 0.0)
        core_width = self.to_float(layout.get("core_bounding_width"), 0.0)
        core_height = self.to_float(layout.get("core_bounding_height"), 0.0)
        num_pdn = self.to_float(statis.get("num_pdn"), 0.0)
        num_clock = self.to_float(nets.get("num_clock"), 0.0)
        num_routing_layers = self.to_float(
            layers.get("num_layers_routing", statis.get("num_layers_routing")),
            0.0,
        )

        checks = [
            (
                "Area",
                "check DIE area",
                die_area is not None
                and die_width is not None
                and die_height is not None
                and die_area > 0
                and die_width > 0
                and die_height > 0,
                die_area_error
                or die_width_error
                or die_height_error
                or "die_area, die_width, and die_height must be greater than zero",
            ),
            (
                "Area",
                "check core area",
                core_area_metric is not None
                and core_area_metric > 0
                and core_area > 0
                and core_width > 0
                and core_height > 0,
                core_area_error
                or "core_area must be positive and floorplan feature must define core bounds",
            ),
            (
                "Area",
                "check core utilization",
                core_util is not None and 0 < core_util <= 1,
                core_util_error or f"core_utilization must be within (0, 1], got {core_util}",
            ),
            (
                "Rows/Tracks",
                "check placement rows and sites",
                subflow_state.get("init floorplan") == "Success"
                and "Write ROWS success" in log_text
                and output_success,
                "Floorplan rows/sites were not written or DEF/verilog/GDS output is missing",
            ),
            (
                "Rows/Tracks",
                "check routing tracks",
                subflow_state.get("create tracks") == "Success"
                and num_routing_layers > 0
                and "Write Track Grid success" in log_text,
                "Routing track subflow, routing layers, or track-grid log evidence is missing",
            ),
            (
                "Pins/Macros",
                "check IO pin placement",
                subflow_state.get("place io pins") == "Success"
                and num_iopins is not None
                and num_iopins > 0
                and "Write PINS success" in log_text,
                io_pin_error or "IO pin placement subflow or PINS output evidence is missing",
            ),
            (
                "Pins/Macros",
                "check macro placement",
                "Macros" in db and "Macros Statis" in db and output_success,
                "Macro feature sections or floorplan output files are missing",
            ),
            (
                "PDN",
                "check tap and endcap insertion",
                subflow_state.get("tap cell") == "Success"
                and "Write COMPONENTS success" in log_text,
                "Tap-cell subflow or COMPONENTS output evidence is missing",
            ),
            (
                "PDN",
                "check PDN IO and global connect",
                subflow_state.get("PDN") == "Success" and num_pdn >= 2,
                f"PDN subflow is incomplete or feature reports only {num_pdn} PDN entries",
            ),
            (
                "PDN",
                "check PDN grid and stripes",
                subflow_state.get("PDN") == "Success" and "Write SPECIALNETS success" in log_text,
                "PDN subflow or SPECIALNETS output evidence is missing",
            ),
            (
                "Clock",
                "check clock net type",
                subflow_state.get("set clock net") == "Success" and num_clock > 0,
                f"Clock-net subflow is incomplete or feature reports {num_clock} clock nets",
            ),
        ]

        warning_items = {"check macro placement"}
        return self.apply_checks(step, checks, warning_items)


class EccNetlistOptChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.NETLIST_OPT.value
        metrics = self.qor_metrics()
        db = json_read(self.workspace_step.feature.db or "")
        config = json_read(self.workspace.config.get(StepEnum.NETLIST_OPT.value, ""))

        try:
            with open(
                self.workspace_step.output.verilog or "",
                encoding="utf-8",
                errors="ignore",
            ) as file:
                netlist_text = file.read()
        except OSError:
            netlist_text = ""

        statis = db.get("Design Statis", {})
        buffer_cells = getattr(self.workspace.pdk, "buffers", []) or []
        tie_high = getattr(self.workspace.pdk, "tie_high_cell", "")
        tie_low = getattr(self.workspace.pdk, "tie_low_cell", "")
        max_fanout_limit = self.to_float(
            config.get("max_fanout", self.workspace.parameters.data.get("max_fanout")),
            0.0,
        )
        actual_max_fanout, fanout_error = metrics.number("fanout_max")
        total_nets, net_count_error = metrics.number("net_count")
        db_nets = self.to_float(statis.get("num_nets"), 0.0)
        output_success = all(
            [
                self.check_file(self.workspace_step.output.def_ or ""),
                self.check_file(self.workspace_step.output.verilog or ""),
                self.check_file(self.workspace_step.output.gds or ""),
            ]
        )

        buffer_success = len(buffer_cells) > 0 and (
            any(buffer in netlist_text for buffer in buffer_cells)
            or config.get("insert_buffer") in buffer_cells
        )
        tie_success = bool(tie_high and tie_low)
        if (tie_high and tie_high in netlist_text) or (tie_low and tie_low in netlist_text):
            tie_success = True

        checks = [
            (
                "Fanout",
                "check max fanout constraint",
                max_fanout_limit > 0,
                "max_fanout is missing or invalid in fixFanout configuration",
            ),
            (
                "Fanout",
                "check high fanout nets",
                actual_max_fanout is not None
                and max_fanout_limit > 0
                and actual_max_fanout <= max_fanout_limit,
                fanout_error
                or f"fanout_max={actual_max_fanout} exceeds configured limit {max_fanout_limit}",
            ),
            (
                "Buffer",
                "check inserted buffer type",
                buffer_success,
                "Configured buffer type is absent from the repaired netlist",
            ),
            (
                "Tie",
                "check tie cell usage",
                tie_success,
                "Tie high/low cells are neither configured nor present in the repaired netlist",
            ),
            (
                "Netlist",
                "check netlist and DEF consistency",
                output_success
                and total_nets is not None
                and total_nets > 0
                and db_nets > 0
                and int(total_nets) == int(db_nets),
                net_count_error
                or (
                    f"Output DEF/verilog/GDS is missing or net_count={total_nets} "
                    f"does not match feature net count {db_nets}"
                ),
            ),
        ]

        warning_items = {"check high fanout nets", "check tie cell usage"}
        return self.apply_checks(step, checks, warning_items)


class EccCtsChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.CTS.value
        metrics = self.qor_metrics()
        db = json_read(self.workspace_step.feature.db or "")
        config = json_read(self.workspace.config.get(StepEnum.CTS.value, ""))

        nets = db.get("Nets", {})
        instances = db.get("Instances", {})
        clock_instances = instances.get("clock", {}) or {}
        buffer_cells = config.get("buffer_type", [])
        if isinstance(buffer_cells, str):
            buffer_cells = [buffer_cells]

        num_clock = self.to_float(nets.get("num_clock"), 0.0)
        clock_sink_num = self.to_float(clock_instances.get("num"), 0.0)
        buffer_num, buffer_error = metrics.number("cts_buffer_count")
        clock_path_max, path_max_error = metrics.number("clock_path_max_buffer")
        clock_path_min, path_min_error = metrics.number("clock_path_min_buffer")
        clock_wirelength, wirelength_error = metrics.number("clock_wirelength")
        optimized_skew, skew_error = metrics.number("cts_worst_optimized_skew_ns")
        unmet_skew, unmet_skew_error = metrics.number("cts_skew_target_unmet_count")
        skew_bound = self.to_float(config.get("skew_bound"), 0.0)
        max_transition = self.to_float(config.get("max_buf_tran", config.get("max_sink_tran")), 0.0)
        max_cap = self.to_float(config.get("max_cap"), 0.0)

        checks = [
            (
                "Clock",
                "check clock net",
                num_clock > 0,
                f"CTS feature reports {num_clock} clock nets",
            ),
            (
                "Buffer",
                "check CTS buffers",
                len(buffer_cells) > 0 and buffer_num is not None and buffer_num > 0,
                buffer_error or "CTS buffer types are not configured or cts_buffer_count is zero",
            ),
            (
                "Timing",
                "check clock skew",
                skew_bound > 0
                and optimized_skew is not None
                and unmet_skew is not None
                and optimized_skew <= skew_bound
                and unmet_skew == 0,
                skew_error
                or unmet_skew_error
                or (
                    f"optimized skew={optimized_skew} ns, target={skew_bound} ns, "
                    f"unmet clocks={unmet_skew}"
                ),
            ),
            (
                "Timing",
                "check clock transition",
                False,
                "Current CTS V3 analysis does not emit measured clock transition data "
                f"(configured limit is {max_transition})",
            ),
            (
                "Timing",
                "check clock capacitance",
                False,
                "Current CTS V3 analysis does not emit measured clock capacitance data "
                f"(configured limit is {max_cap})",
            ),
            (
                "Tree",
                "check clock sink coverage",
                clock_sink_num > 0
                and clock_path_max is not None
                and clock_path_min is not None
                and clock_path_max >= clock_path_min > 0
                and clock_wirelength is not None
                and clock_wirelength > 0,
                path_max_error
                or path_min_error
                or wirelength_error
                or (
                    f"Clock sinks={clock_sink_num}, path depth min/max="
                    f"{clock_path_min}/{clock_path_max}, wirelength={clock_wirelength}"
                ),
            ),
        ]

        return self.apply_checks(
            step,
            checks,
            {"check clock transition", "check clock capacitance"},
        )


class EccRoutingChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.ROUTING.value
        metrics = self.qor_metrics()
        db = json_read(self.workspace_step.feature.db or "")
        feature = json_read(self.workspace_step.feature.step or "").get(StepEnum.ROUTING.value, {})
        config = json_read(self.workspace.config.get(StepEnum.ROUTING.value, ""))

        layers = db.get("Layers", {})
        nets = db.get("Nets", {})
        rt_config = config.get("RT", {})
        routing_layer_names = [
            layer.get("layer_name") for layer in layers.get("routing_layers", [])
        ]
        bottom_layer = rt_config.get("-bottom_routing_layer")
        top_layer = rt_config.get("-top_routing_layer")
        dr_iterations = feature.get("DR", [])
        total_nets = self.to_float(nets.get("num_total"), 0.0)
        final_violation_num, violation_error = metrics.number("route_dr_total_violation_count")
        wire_len, wirelength_error = metrics.number("route_wirelength")
        via_num, via_error = metrics.number("route_via_count")
        timing_enabled = str(rt_config.get("-enable_timing", "0")) == "1"
        output_success = all(
            [
                self.check_file(self.workspace_step.output.def_ or ""),
                self.check_file(self.workspace_step.output.verilog or ""),
                self.check_file(self.workspace_step.output.gds or ""),
            ]
        )

        checks = [
            (
                "Layer",
                "check routing layer range",
                bottom_layer in routing_layer_names and top_layer in routing_layer_names,
                f"Configured routing range {bottom_layer}..{top_layer} "
                "is absent from route feature layers",
            ),
            (
                "Route",
                "check unrouted nets",
                output_success and total_nets > 0 and len(dr_iterations) > 0,
                f"Route output is incomplete, feature net count is {total_nets}, "
                "or DR iterations are missing",
            ),
            (
                "Route",
                "check shorts and opens",
                final_violation_num is not None and final_violation_num == 0,
                violation_error or f"route_dr_total_violation_count={final_violation_num}",
            ),
            (
                "Route",
                "check via count",
                via_num is not None and via_num > 0,
                via_error or f"route_via_count must be positive, got {via_num}",
            ),
            (
                "Route",
                "check wire length",
                wire_len is not None and wire_len > 0,
                wirelength_error or f"route_wirelength must be positive, got {wire_len}",
            ),
            (
                "Timing",
                "check post-route timing",
                not timing_enabled,
                "Post-route timing is enabled but Route V3 analysis has no STA timing metric; "
                "use the STA step structured timing results",
            ),
        ]

        warning_items = {"check post-route timing"}
        return self.apply_checks(step, checks, warning_items)


class EccDrcChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.DRC.value
        metrics = self.qor_metrics()
        feature = json_read(self.workspace_step.feature.step or "").get("drc", {})
        output_success = all(
            [
                self.check_file(self.workspace_step.output.def_ or ""),
                self.check_file(self.workspace_step.output.verilog or ""),
                self.check_file(self.workspace_step.output.gds or ""),
            ]
        )

        metric_drc_num, metric_error = metrics.number("drc_count")
        feature_drc_num = self.to_float(feature.get("number"))
        distribution = feature.get("distribution")
        drc_clean = (
            metric_drc_num is not None
            and feature_drc_num is not None
            and metric_drc_num == 0
            and feature_drc_num == 0
        )

        checks = [
            (
                "DRC",
                "check DRC violation count",
                drc_clean,
                metric_error
                or (
                    f"drc_count={metric_drc_num} and feature/drc.step.json reports "
                    f"{feature_drc_num} violations"
                ),
            ),
            (
                "DRC",
                "check DRC violation distribution",
                drc_clean or isinstance(distribution, dict),
                "drc.step.json has violations but no structured rule/layer distribution",
            ),
            (
                "DRC",
                "check DRC waiver list",
                drc_clean,
                "Current DRC flow has no structured waiver list; "
                "unresolved violations require review",
            ),
            (
                "Signoff",
                "check final DRC requirement",
                output_success and drc_clean,
                "Final DRC requires DEF/verilog/GDS output and zero matching V3/feature violations",
            ),
        ]

        warning_items = {
            "check DRC violation distribution",
            "check DRC waiver list",
        }
        return self.apply_checks(step, checks, warning_items)


class EccFillerChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.FILLER.value
        db = json_read(self.workspace_step.feature.db or "")
        subflow = json_read(self.workspace_step.subflow.path or "")
        config = json_read(self.workspace.config.get(StepEnum.FILLER.value, ""))

        try:
            with open(
                self.workspace_step.log.file or "", encoding="utf-8", errors="ignore"
            ) as file:
                log_text = file.read()
        except OSError:
            log_text = ""

        subflow_state = {item.get("name"): item.get("state") for item in subflow.get("steps", [])}
        min_filler_width = config.get("-min_filler_width", 1)
        pdk_fillers = getattr(self.workspace.pdk, "fillers", []) or []
        output_success = all(
            [
                self.check_file(self.workspace_step.output.def_ or ""),
                self.check_file(self.workspace_step.output.verilog or ""),
                self.check_file(self.workspace_step.output.gds or ""),
            ]
        )
        statis = db.get("Design Statis", {})
        num_instances = self.to_float(statis.get("num_instances"), 0.0)
        log_lower = log_text.lower()
        log_success = not any(
            token in log_lower for token in ["error:", "fatal", "traceback", "exception", "failed"]
        )

        checks = [
            (
                "Filler",
                "check filler cell list",
                len(pdk_fillers) > 0 or int(min_filler_width or 0) > 0,
            ),
            (
                "Filler",
                "check filler coverage",
                subflow_state.get("run filler") == "Success"
                and output_success
                and "insertFiller" in log_text,
            ),
            (
                "Legality",
                "check filler overlap",
                output_success and num_instances > 0 and log_success,
            ),
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

        self.workspace_step.checklist.checklist = Checklist(
            path=self.workspace_step.checklist.path or ""
        ).data

        return all(success for _, _, success in checks)


class EccHardenChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.HARDEN.value
        metrics = self.qor_metrics()
        design_name = self.workspace.design.top_module or self.workspace.design.name

        lef_tokens = ["MACRO", "END LIBRARY"]
        lib_tokens = ["library", "cell"]
        if design_name:
            lef_tokens.append(f"MACRO {design_name}")
            lib_tokens.append(f"cell ({design_name})")

        lef_metric, lef_error = metrics.number("harden_lef_exists")
        lib_metric, lib_error = metrics.number("harden_lib_exists")
        gds_metric, gds_error = metrics.number("harden_gds_exists")

        checks = [
            (
                "Output",
                "check abstract LEF",
                lef_metric == 1
                and self.check_file(self.workspace_step.output.lef or "", lef_tokens),
                lef_error or "harden_lef_exists is not 1 or the LEF deliverable is missing/invalid",
            ),
            (
                "Output",
                "check timing model LIB",
                lib_metric == 1
                and self.check_file(self.workspace_step.output.lib or "", lib_tokens),
                lib_error or "harden_lib_exists is not 1 or the LIB deliverable is missing/invalid",
            ),
            (
                "Output",
                "check harden GDS",
                gds_metric == 1 and self.check_file(self.workspace_step.output.gds or ""),
                gds_error or "harden_gds_exists is not 1 or the GDS deliverable is missing",
            ),
        ]

        deliverables_success = all(success for _, _, success, _ in checks)
        checks.append(
            (
                "Output",
                "check hard macro deliverables",
                deliverables_success,
                "One or more required Harden LEF, LIB, or GDS deliverables failed validation",
            )
        )

        self.apply_checks(step, checks)
        return deliverables_success


class EccRcxChecklist(EccChecklist):
    def collect_rcx_spef_paths(self) -> list:
        spef_value = self.workspace_step.output.spef
        # Preserve the legacy live-list contract: for the list case, extend the
        # step's own list in place (a later reader of step.output.spef sees the
        # discovered output-dir SPEFs); only the legacy string case is wrapped
        # into a fresh local list.
        spef_paths: list = [spef_value] if isinstance(spef_value, str) else spef_value

        output_dir = self.workspace_step.output.dir or ""
        if output_dir and os.path.isdir(output_dir):
            spef_paths.extend(glob.glob(os.path.join(output_dir, "*.spef")))

        return sorted({path for path in spef_paths if path})

    def spef_corner_name(self, spef_path: str) -> str:
        design_name = self.workspace.design.top_module or self.workspace.design.name
        name = os.path.basename(spef_path)
        if name.endswith(".spef"):
            name = name[:-5]

        prefix = f"{design_name}_" if design_name else ""
        if prefix and name.startswith(prefix):
            name = name[len(prefix) :]

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

    def check_spef_file(self, spef_path: str) -> bool:
        design_name = self.workspace.design.top_module or self.workspace.design.name
        tokens = ["*SPEF", "*DESIGN", "*NAME_MAP"]
        if design_name:
            tokens.append(f'*DESIGN "{design_name}"')

        return self.check_file(spef_path, tokens)

    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)

        step = StepEnum.RCX.value
        spef_paths = self.collect_rcx_spef_paths()
        required_rcx_corners = self.sta_required_rcx_corners()
        extracted_corners = {self.spef_corner_name(path) for path in spef_paths}

        metrics = self.qor_metrics()
        expected_count, expected_error = metrics.number("rcx_expected_corner_count")
        missing_count, missing_error = metrics.number("rcx_missing_corner_count")
        spef_count, spef_count_error = metrics.number("rcx_spef_file_count")
        parse_failure_count, parse_error = metrics.number("rcx_spef_parse_failure_count")
        output_def, output_def_error = metrics.number("rcx_output_def_exists")
        output_gds, output_gds_error = metrics.number("rcx_output_gds_exists")
        corners_success = (
            expected_count is not None
            and expected_count > 0
            and missing_count is not None
            and missing_count == 0
            and spef_count is not None
            and spef_count == expected_count
            and parse_failure_count is not None
            and parse_failure_count == 0
        )
        spef_files_success = (
            len(spef_paths) > 0
            and all(os.path.isfile(path) and os.path.getsize(path) > 0 for path in spef_paths)
            and spef_count is not None
            and len(spef_paths) == int(spef_count)
        )

        spef_net_names_success = len(spef_paths) > 0 and all(
            self.check_spef_file(path) for path in spef_paths
        )

        if required_rcx_corners:
            mapping_success = required_rcx_corners.issubset(extracted_corners)
        else:
            mapping_success = len(extracted_corners) > 0

        checks = [
            (
                "RCX",
                "check RCX corners",
                corners_success,
                expected_error
                or missing_error
                or spef_count_error
                or parse_error
                or (
                    f"expected={expected_count}, available={spef_count}, missing={missing_count}, "
                    f"parse failures={parse_failure_count}"
                ),
            ),
            (
                "RCX",
                "check SPEF files",
                spef_files_success,
                spef_count_error
                or (
                    f"RCX output has {len(spef_paths)} SPEF files but qor_metrics "
                    f"reports {spef_count}"
                ),
            ),
            (
                "RCX",
                "check SPEF net names",
                spef_net_names_success,
                "One or more SPEF files are missing *SPEF, *DESIGN, or *NAME_MAP content",
            ),
            (
                "STA",
                "check RCX and STA corner mapping",
                mapping_success and output_def == 1 and output_gds == 1,
                output_def_error
                or output_gds_error
                or (
                    f"STA requires {sorted(required_rcx_corners)}, RCX provides "
                    f"{sorted(extracted_corners)}, output DEF/GDS flags={output_def}/{output_gds}"
                ),
            ),
        ]

        return self.apply_checks(step, checks)


class EccStaChecklist(EccChecklist):
    def check(self) -> bool:
        return refresh_step_checklist(self.workspace, self.workspace_step)
