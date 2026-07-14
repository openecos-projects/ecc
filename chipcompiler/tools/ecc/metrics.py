#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from math import isfinite
from pathlib import Path

from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    StepMetrics, 
    save_metrics,
    StepEnum,
    StateEnum
)
from chipcompiler.utility import json_read, json_write, dict_to_str

from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.tools.ecc.sta_qor import (
    STA_QOR_SUMMARY_FILENAME,
    read_sta_qor_summary,
    sta_qor_summary_paths,
)


QOR_METRIC_MAP = {
    "Cell area": {
        "name": "synthesis_cell_area",
        "display_name": "Synthesis Cell Area",
        "unit": "um^2",
        "dimension": "area_cost",
        "polarity": "lower_is_better",
    },
    "Cell number": {
        "name": "synthesis_cell_count",
        "display_name": "Synthesis Cell Count",
        "unit": "count",
        "dimension": "area_cost",
        "polarity": "trend_only",
    },
    "Wire number": {
        "name": "synthesis_wire_count",
        "display_name": "Synthesis Wire Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "Port number": {
        "name": "synthesis_port_count",
        "display_name": "Synthesis Port Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "Die area [μm^2]": {
        "name": "die_area",
        "display_name": "Die Area",
        "unit": "um^2",
        "dimension": "area_cost",
        "polarity": "lower_is_better",
    },
    "Core area [μm^2]": {
        "name": "core_area",
        "display_name": "Core Area",
        "unit": "um^2",
        "dimension": "area_cost",
        "polarity": "lower_is_better",
    },
    "Die width [um]": {
        "name": "die_width",
        "display_name": "Die Width",
        "unit": "um",
        "dimension": "area_cost",
        "polarity": "trend_only",
    },
    "Die height [um]": {
        "name": "die_height",
        "display_name": "Die Height",
        "unit": "um",
        "dimension": "area_cost",
        "polarity": "trend_only",
    },
    "Die util": {
        "name": "die_utilization",
        "display_name": "Die Utilization",
        "unit": "ratio",
        "dimension": "area_cost",
        "polarity": "target_range",
    },
    "Core util": {
        "name": "core_utilization",
        "display_name": "Core Utilization",
        "unit": "ratio",
        "dimension": "area_cost",
        "polarity": "target_range",
    },
    "Total io pins": {
        "name": "io_pin_count",
        "display_name": "IO Pin Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "Total instances": {
        "name": "instance_count",
        "display_name": "Instance Count",
        "unit": "count",
        "dimension": "area_cost",
        "polarity": "trend_only",
    },
    "Total nets": {
        "name": "net_count",
        "display_name": "Net Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "Max fanout": {
        "name": "fanout_max",
        "display_name": "Max Fanout",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "overflow": {
        "name": "place_overflow",
        "display_name": "Place Overflow",
        "unit": "ratio",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "overflow_number": {
        "name": "place_overflow_count",
        "display_name": "Place Overflow Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "bin_number": {
        "name": "place_bin_count",
        "display_name": "Place Bin Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "GP HPWL": {
        "name": "place_hpwl",
        "display_name": "Place HPWL",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "DP HPWL": {
        "name": "place_hpwl",
        "display_name": "Place HPWL",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "HPWL": {
        "name": "place_hpwl",
        "display_name": "Place HPWL",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "GRWL": {
        "name": "place_grwl",
        "display_name": "Place GRWL",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "FLUTE": {
        "name": "place_flute_wirelength",
        "display_name": "Place FLUTE Wirelength",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "place_congestion_egr_overflow_total": {
        "name": "place_congestion_egr_overflow_total",
        "display_name": "Place EGR Overflow Total",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "place_congestion_egr_overflow_max": {
        "name": "place_congestion_egr_overflow_max",
        "display_name": "Place EGR Overflow Max",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "place_rudy_utilization_max": {
        "name": "place_rudy_utilization_max",
        "display_name": "Place RUDY Utilization Max",
        "unit": "ratio",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "place_lutrudy_utilization_max": {
        "name": "place_lutrudy_utilization_max",
        "display_name": "Place LUT-RUDY Utilization Max",
        "unit": "ratio",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "buffer_num": {
        "name": "cts_buffer_count",
        "display_name": "CTS Buffer Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "buffer_area": {
        "name": "cts_buffer_area",
        "display_name": "CTS Buffer Area",
        "unit": "um^2",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "clock_path_max_buffer": {
        "name": "clock_path_max_buffer",
        "display_name": "Clock Path Max Buffer",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "clock_path_min_buffer": {
        "name": "clock_path_min_buffer",
        "display_name": "Clock Path Min Buffer",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "trend_only",
    },
    "total_clock_wirelength": {
        "name": "clock_wirelength",
        "display_name": "Clock Wirelength",
        "unit": "um",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "max_clock_wirelength": {
        "name": "cts_clock_wirelength_max",
        "display_name": "CTS Max Clock Wirelength",
        "unit": "um",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "max_level_of_clock_tree": {
        "name": "cts_clock_tree_max_level",
        "display_name": "CTS Clock Tree Max Level",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "total_movement": {
        "name": "legal_total_movement",
        "display_name": "Legal Total Movement",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "wire_len": {
        "name": "route_wirelength",
        "display_name": "Route Wirelength",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "num_via": {
        "name": "route_via_count",
        "display_name": "Route Via Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "drc_num": {
        "name": "drc_count",
        "display_name": "DRC Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "route_dr_total_violation_count": {
        "name": "route_dr_total_violation_count",
        "display_name": "Route DR Violations",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "route_dr_total_patch_count": {
        "name": "route_dr_total_patch_count",
        "display_name": "Route DR Patches",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "route_dr_total_wirelength": {
        "name": "route_dr_total_wirelength",
        "display_name": "Route DR Wirelength",
        "unit": "um",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "route_dr_total_via_count": {
        "name": "route_dr_total_via_count",
        "display_name": "Route DR Via Count",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "route_la_total_overflow": {
        "name": "route_la_total_overflow",
        "display_name": "Route LA Overflow",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "lower_is_better",
    },
    "route_la_total_demand": {
        "name": "route_la_total_demand",
        "display_name": "Route LA Demand",
        "unit": "count",
        "dimension": "routability_physical",
        "polarity": "trend_only",
    },
    "rcx_spef_file_count": {
        "name": "rcx_spef_file_count",
        "display_name": "RCX SPEF File Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "trend_only",
    },
    "rcx_expected_corner_count": {
        "name": "rcx_expected_corner_count",
        "display_name": "RCX Expected Corner Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "trend_only",
    },
    "rcx_missing_corner_count": {
        "name": "rcx_missing_corner_count",
        "display_name": "RCX Missing Corner Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "rcx_output_def_exists": {
        "name": "rcx_output_def_exists",
        "display_name": "RCX DEF Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "rcx_output_gds_exists": {
        "name": "rcx_output_gds_exists",
        "display_name": "RCX GDS Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "max_WNS": {
        "name": "sta_setup_wns",
        "display_name": "STA Setup WNS",
        "unit": "ns",
        "dimension": "timing",
        "polarity": "higher_is_better",
    },
    "max_TNS": {
        "name": "sta_setup_tns",
        "display_name": "STA Setup TNS",
        "unit": "ns",
        "dimension": "timing",
        "polarity": "higher_is_better",
    },
    "min_WNS": {
        "name": "sta_hold_wns",
        "display_name": "STA Hold WNS",
        "unit": "ns",
        "dimension": "timing",
        "polarity": "higher_is_better",
    },
    "min_TNS": {
        "name": "sta_hold_tns",
        "display_name": "STA Hold TNS",
        "unit": "ns",
        "dimension": "timing",
        "polarity": "higher_is_better",
    },
    "Frequency [MHz]": {
        "name": "sta_frequency_mhz",
        "display_name": "STA Frequency",
        "unit": "MHz",
        "dimension": "timing",
        "polarity": "higher_is_better",
    },
    "sta_corner_count": {
        "name": "sta_corner_count",
        "display_name": "STA Corner Count",
        "unit": "count",
        "dimension": "timing",
        "polarity": "trend_only",
    },
    "sta_expected_corner_count": {
        "name": "sta_expected_corner_count",
        "display_name": "STA Expected Corner Count",
        "unit": "count",
        "dimension": "timing",
        "polarity": "trend_only",
    },
    "sta_missing_corner_count": {
        "name": "sta_missing_corner_count",
        "display_name": "STA Missing Corner Count",
        "unit": "count",
        "dimension": "timing",
        "polarity": "lower_is_better",
    },
    "setup_violation_count": {
        "name": "sta_setup_violation_count",
        "display_name": "STA Setup Violation Count",
        "unit": "count",
        "dimension": "timing",
        "polarity": "lower_is_better",
    },
    "hold_violation_count": {
        "name": "sta_hold_violation_count",
        "display_name": "STA Hold Violation Count",
        "unit": "count",
        "dimension": "timing",
        "polarity": "lower_is_better",
    },
    "harden_gds_exists": {
        "name": "harden_gds_exists",
        "display_name": "Harden GDS Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "harden_lef_exists": {
        "name": "harden_lef_exists",
        "display_name": "Harden LEF Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "harden_lib_exists": {
        "name": "harden_lib_exists",
        "display_name": "Harden LIB Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "harden_lib_check_exists": {
        "name": "harden_lib_check_exists",
        "display_name": "Harden LIB Check Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "harden_preview_exists": {
        "name": "harden_preview_exists",
        "display_name": "Harden Preview Exists",
        "unit": "boolean",
        "dimension": "clock_robustness_dfm",
        "polarity": "higher_is_better",
    },
    "harden_artifact_missing_count": {
        "name": "harden_artifact_missing_count",
        "display_name": "Harden Missing Artifact Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
}

QOR_BLOCKING_METRIC_REASONS = {
    "drc_count": "DRC violations are present.",
    "route_dr_total_violation_count": "Route detailed routing violations are present.",
    "route_la_total_overflow": "Route layer assignment overflow is present.",
    "rcx_missing_corner_count": "RCX expected SPEF corners are missing.",
    "sta_setup_wns": "STA setup WNS is negative.",
    "sta_setup_tns": "STA setup TNS is negative.",
    "sta_hold_wns": "STA hold WNS is negative.",
    "sta_hold_tns": "STA hold TNS is negative.",
    "sta_setup_violation_count": "STA setup violating paths are present.",
    "sta_hold_violation_count": "STA hold violating paths are present.",
    "sta_missing_corner_count": "STA QoR summaries are missing for configured corners.",
    "harden_artifact_missing_count": "Harden output artifacts are missing.",
}

QOR_HOTSPOT_METRIC_HINTS = {
    "place_congestion_egr_overflow_total": {
        "kind": "congestion",
        "severity": "warning",
        "description": "Placement EGR overflow is present.",
    },
    "place_congestion_egr_overflow_max": {
        "kind": "congestion",
        "severity": "warning",
        "description": "Placement EGR overflow peak is present.",
    },
    "place_rudy_utilization_max": {
        "kind": "congestion",
        "severity": "warning",
        "description": "Placement RUDY utilization peak is present.",
    },
    "place_lutrudy_utilization_max": {
        "kind": "congestion",
        "severity": "warning",
        "description": "Placement LUT-RUDY utilization peak is present.",
    },
    "route_la_total_overflow": {
        "kind": "routing_overflow",
        "severity": "critical",
        "description": "Route layer assignment overflow is present.",
    },
    "route_dr_total_violation_count": {
        "kind": "routing_violation",
        "severity": "critical",
        "description": "Route detailed routing violations are present.",
    },
}

QOR_EXPECTED_METRICS_BY_STEP = {
    StepEnum.SYNTHESIS.value: [
        "synthesis_cell_area",
        "synthesis_cell_count",
        "synthesis_wire_count",
        "synthesis_port_count",
    ],
    StepEnum.FLOORPLAN.value: [
        "die_area",
        "die_width",
        "die_height",
        "die_utilization",
        "core_utilization",
        "io_pin_count",
        "instance_count",
        "net_count",
    ],
    StepEnum.NETLIST_OPT.value: [
        "die_area",
        "die_width",
        "die_height",
        "die_utilization",
        "core_utilization",
        "io_pin_count",
        "instance_count",
        "net_count",
        "fanout_max",
    ],
    StepEnum.PLACEMENT.value: [
        "place_overflow",
        "place_overflow_count",
        "place_bin_count",
        "place_hpwl",
        "place_grwl",
        "place_flute_wirelength",
        "place_congestion_egr_overflow_total",
        "place_congestion_egr_overflow_max",
        "place_rudy_utilization_max",
        "place_lutrudy_utilization_max",
    ],
    StepEnum.CTS.value: [
        "cts_buffer_count",
        "cts_buffer_area",
        "clock_path_max_buffer",
        "clock_path_min_buffer",
        "clock_wirelength",
        "cts_clock_wirelength_max",
        "cts_clock_tree_max_level",
    ],
    StepEnum.LEGALIZATION.value: [
        "legal_total_movement",
    ],
    StepEnum.ROUTING.value: [
        "route_wirelength",
        "route_via_count",
        "route_dr_total_violation_count",
        "route_dr_total_patch_count",
        "route_dr_total_wirelength",
        "route_dr_total_via_count",
        "route_la_total_overflow",
        "route_la_total_demand",
    ],
    StepEnum.DRC.value: [
        "drc_count",
    ],
    StepEnum.RCX.value: [
        "rcx_spef_file_count",
        "rcx_expected_corner_count",
        "rcx_missing_corner_count",
        "rcx_output_def_exists",
        "rcx_output_gds_exists",
    ],
    StepEnum.STA.value: [
        "sta_setup_wns",
        "sta_setup_tns",
        "sta_hold_wns",
        "sta_hold_tns",
        "sta_frequency_mhz",
        "sta_corner_count",
        "sta_expected_corner_count",
        "sta_missing_corner_count",
        "sta_setup_violation_count",
        "sta_hold_violation_count",
    ],
    StepEnum.HARDEN.value: [
        "harden_gds_exists",
        "harden_lef_exists",
        "harden_lib_exists",
        "harden_lib_check_exists",
        "harden_preview_exists",
        "harden_artifact_missing_count",
    ],
}


def _qor_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        percent = text.endswith("%")
        if percent:
            text = text[:-1].strip()
        text = text.replace(",", "")
        try:
            number = float(text)
        except ValueError:
            return None
        if percent:
            number = number / 100.0
    else:
        return None

    if not isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _scaled_qor_number(value, scale: float = 1.0):
    number = _qor_number(value)
    if number is None:
        return None

    scaled = float(number) * scale
    if not isfinite(scaled):
        return None
    if scale == 1.0:
        return int(scaled) if scaled.is_integer() else scaled

    rounded = round(scaled, 6)
    return int(rounded) if float(rounded).is_integer() else rounded


def _add_number_metric(metrics: dict, key: str, value, scale: float = 1.0) -> None:
    number = _scaled_qor_number(value, scale=scale)
    if number is not None:
        metrics[key] = number


def _latest_route_iteration(items):
    if not isinstance(items, list):
        return None

    latest = None
    latest_iter = None
    for item in items:
        if not isinstance(item, dict):
            continue
        item_iter = _qor_number(item.get("iter"))
        if latest is None:
            latest = item
            latest_iter = item_iter
        elif item_iter is None:
            latest = item
        elif latest_iter is None or item_iter >= latest_iter:
            latest = item
            latest_iter = item_iter

    return latest


def _existing_files_in(directory, pattern: str) -> list[Path]:
    try:
        path = Path(directory)
    except TypeError:
        return []

    if not path.is_dir():
        return []
    return sorted(item for item in path.glob(pattern) if item.is_file())


def _path_exists(path) -> bool:
    if path is None or path == "":
        return False
    return Path(path).is_file()


def _artifact_exists(primary_path, output_dir, pattern: str) -> int:
    if _path_exists(primary_path):
        return 1
    return 1 if _existing_files_in(output_dir, pattern) else 0


STA_QOR_CORNER_FIELDS = {
    "max_WNS": "sta_worst_setup_corner",
    "max_TNS": "sta_worst_setup_tns_corner",
    "min_WNS": "sta_worst_hold_corner",
    "min_TNS": "sta_worst_hold_tns_corner",
    "Frequency [MHz]": "sta_worst_frequency_corner",
    "setup_violation_count": "sta_corner_scope",
    "hold_violation_count": "sta_corner_scope",
    "sta_corner_count": "sta_corner_scope",
    "sta_expected_corner_count": "sta_corner_scope",
    "sta_missing_corner_count": "sta_corner_scope",
}


def _sta_qor_record_corner(step_metrics: StepMetrics, legacy_name: str) -> str | None:
    corner_key = STA_QOR_CORNER_FIELDS.get(legacy_name)
    if corner_key is None:
        return None

    corner = step_metrics.data.get(corner_key)
    return corner if isinstance(corner, str) and corner else None


def _sta_qor_source_file(step: WorkspaceStep) -> str | None:
    output_dir = step.output.get("dir")
    if output_dir is None or output_dir == "":
        return None
    return str(Path(output_dir) / "**" / STA_QOR_SUMMARY_FILENAME)


def build_qor_metrics_payload(workspace: Workspace,
                              step: WorkspaceStep,
                              step_metrics: StepMetrics) -> dict:
    records = []
    source_file = str(step_metrics.path)
    for legacy_name, raw_value in step_metrics.data.items():
        mapping = QOR_METRIC_MAP.get(legacy_name)
        if mapping is None:
            continue

        value = _qor_number(raw_value)
        if value is None:
            continue

        record = {
            "name": mapping["name"],
            "display_name": mapping["display_name"],
            "value": value,
            "unit": mapping["unit"],
            "dimension": mapping["dimension"],
            "polarity": mapping["polarity"],
            "source_file": source_file,
            "confidence": "high",
        }
        if step.name == StepEnum.STA.value:
            corner = _sta_qor_record_corner(step_metrics, legacy_name)
            if corner is not None:
                record["corner"] = corner
            sta_source_file = _sta_qor_source_file(step)
            if sta_source_file is not None:
                record["source_file"] = sta_source_file
        records.append(record)

    return {
        "schema_version": 1,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "metrics": records,
    }


def _is_blocking_qor_record(record: dict) -> bool:
    metric_name = record.get("name")
    value = _qor_number(record.get("value"))
    if value is None:
        return False

    if metric_name in {
        "drc_count",
        "route_dr_total_violation_count",
        "route_la_total_overflow",
        "rcx_missing_corner_count",
        "sta_setup_violation_count",
        "sta_hold_violation_count",
        "sta_missing_corner_count",
        "harden_artifact_missing_count",
    }:
        return value > 0

    if metric_name in {
        "sta_setup_wns",
        "sta_setup_tns",
        "sta_hold_wns",
        "sta_hold_tns",
    }:
        return value < 0

    return False


def _qor_blocking_issue(record: dict) -> dict | None:
    if not _is_blocking_qor_record(record):
        return None

    metric_name = record.get("name")
    return {
        "metric": metric_name,
        "display_name": record.get("display_name", metric_name),
        "value": record.get("value"),
        "reason": QOR_BLOCKING_METRIC_REASONS.get(
            metric_name,
            "QoR metric is outside the accepted range.",
        ),
    }


def _qor_missing_metrics(step: WorkspaceStep, records: list[dict]) -> list[str]:
    expected_metrics = QOR_EXPECTED_METRICS_BY_STEP.get(step.name, [])
    available_metrics = {
        record.get("name")
        for record in records
        if isinstance(record.get("name"), str)
    }
    return [
        metric_name
        for metric_name in expected_metrics
        if metric_name not in available_metrics
    ]


def _sta_qor_hard_gates(records: list[dict]) -> list[dict]:
    values = {
        record.get("name"): _qor_number(record.get("value"))
        for record in records
    }
    gate_specs = (
        ("sta_setup_wns_clean", "sta_setup_wns", 0.0, lambda value: value >= 0),
        ("sta_setup_tns_clean", "sta_setup_tns", 0.0, lambda value: value >= 0),
        (
            "sta_setup_violation_free",
            "sta_setup_violation_count",
            0.0,
            lambda value: value == 0,
        ),
        ("sta_hold_wns_clean", "sta_hold_wns", 0.0, lambda value: value >= 0),
        ("sta_hold_tns_clean", "sta_hold_tns", 0.0, lambda value: value >= 0),
        (
            "sta_hold_violation_free",
            "sta_hold_violation_count",
            0.0,
            lambda value: value == 0,
        ),
    )
    hard_gates = []
    for gate_id, metric, threshold, predicate in gate_specs:
        actual = values.get(metric)
        hard_gates.append({
            "id": gate_id,
            "passed": actual is not None and predicate(actual),
            "metric": metric,
            "threshold": threshold,
            "actual": actual,
            "cap_if_failed": 70,
        })

    expected_count = values.get("sta_expected_corner_count")
    actual_count = values.get("sta_corner_count")
    hard_gates.append({
        "id": "sta_corner_coverage_complete",
        "passed": (
            expected_count is not None
            and expected_count > 0
            and actual_count == expected_count
        ),
        "metric": "sta_corner_count",
        "threshold": expected_count,
        "actual": actual_count,
        "cap_if_failed": 70,
    })
    return hard_gates


def build_qor_summary_payload(workspace: Workspace,
                              step: WorkspaceStep,
                              step_metrics: StepMetrics) -> dict:
    qor_metrics = build_qor_metrics_payload(
        workspace=workspace,
        step=step,
        step_metrics=step_metrics,
    )
    records = qor_metrics["metrics"]
    dimensions = {}
    blocking_issues = []

    for record in records:
        dimension = record.get("dimension", "unknown")
        dimensions.setdefault(dimension, {"metric_count": 0})
        dimensions[dimension]["metric_count"] += 1

        issue = _qor_blocking_issue(record)
        if issue is not None:
            blocking_issues.append(issue)

    hard_gates = (
        _sta_qor_hard_gates(records)
        if step.name == StepEnum.STA.value
        else []
    )
    failed_hard_gates = [gate for gate in hard_gates if not gate["passed"]]

    if len(records) == 0:
        status = "empty"
    elif blocking_issues or failed_hard_gates:
        status = "blocked"
    else:
        status = "green"

    return {
        "schema_version": 1,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "status": status,
        "metric_count": len(records),
        "dimensions": dimensions,
        "blocking_issues": blocking_issues,
        "hard_gates": hard_gates,
        "missing_metrics": _qor_missing_metrics(step, records),
        "source_file": str(step.analysis.get("qor_metrics", step_metrics.path)),
    }


def _qor_hotspot_record(record: dict, source_file: str) -> dict | None:
    metric_name = record.get("name")
    hint = QOR_HOTSPOT_METRIC_HINTS.get(metric_name)
    if hint is None:
        return None

    value = _qor_number(record.get("value"))
    if value is None or value <= 0:
        return None

    return {
        "kind": hint["kind"],
        "severity": hint["severity"],
        "metric": metric_name,
        "display_name": record.get("display_name", metric_name),
        "value": record.get("value"),
        "unit": record.get("unit"),
        "dimension": record.get("dimension"),
        "source_file": source_file,
        "description": hint["description"],
    }


def build_qor_hotspots_payload(workspace: Workspace,
                               step: WorkspaceStep,
                               step_metrics: StepMetrics) -> dict:
    qor_metrics = build_qor_metrics_payload(
        workspace=workspace,
        step=step,
        step_metrics=step_metrics,
    )
    source_file = str(step.analysis.get("qor_metrics", step_metrics.path))
    hotspots = []

    for record in qor_metrics["metrics"]:
        hotspot = _qor_hotspot_record(record, source_file)
        if hotspot is not None:
            hotspots.append(hotspot)

    return {
        "schema_version": 1,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "source_file": source_file,
        "hotspots": hotspots,
    }


def save_qor_metrics(workspace: Workspace,
                     step: WorkspaceStep,
                     step_metrics: StepMetrics) -> bool:
    qor_metrics_path = step.analysis.get("qor_metrics")
    if qor_metrics_path is None:
        return True

    return json_write(
        file_path=qor_metrics_path,
        data=build_qor_metrics_payload(
            workspace=workspace,
            step=step,
            step_metrics=step_metrics,
        ),
    )


def save_qor_summary(workspace: Workspace,
                     step: WorkspaceStep,
                     step_metrics: StepMetrics) -> bool:
    qor_summary_path = step.analysis.get("qor_summary")
    if qor_summary_path is None:
        return True

    return json_write(
        file_path=qor_summary_path,
        data=build_qor_summary_payload(
            workspace=workspace,
            step=step,
            step_metrics=step_metrics,
        ),
    )


def save_qor_hotspots(workspace: Workspace,
                      step: WorkspaceStep,
                      step_metrics: StepMetrics) -> bool:
    qor_hotspots_path = step.analysis.get("qor_hotspots")
    if qor_hotspots_path is None:
        return True

    return json_write(
        file_path=qor_hotspots_path,
        data=build_qor_hotspots_payload(
            workspace=workspace,
            step=step,
            step_metrics=step_metrics,
        ),
    )


def save_step_metrics(workspace: Workspace,
                      step: WorkspaceStep,
                      step_metrics: StepMetrics) -> bool:
    if not save_metrics(step_metrics):
        return False
    if not save_qor_metrics(workspace=workspace, step=step, step_metrics=step_metrics):
        return False
    if not save_qor_summary(workspace=workspace, step=step, step_metrics=step_metrics):
        return False
    return save_qor_hotspots(workspace=workspace, step=step, step_metrics=step_metrics)


def build_step_metrics(workspace: Workspace, 
                       step: WorkspaceStep,
                       subflow: EccSubFlow = None) -> StepMetrics:
    """
    Build and return a StepMetrics instance for the given workspace step.
    """
    # update sub flow metrics state
    sub_flow = subflow if subflow is not None else EccSubFlow(workspace=workspace, workspace_step=step)
    
    # step matrics
    metrics = None
    match(step.name):
        case StepEnum.FLOORPLAN.value:
            metrics = build_metrics_floorplan(workspace, step)
        case StepEnum.NETLIST_OPT.value:
            metrics = build_metrics_net_opt(workspace, step)
        case StepEnum.PLACEMENT.value:
            metrics = build_metrics_placement(workspace, step)
        case StepEnum.CTS.value:
            metrics = build_metrics_cts(workspace, step)
        case StepEnum.TIMING_OPT_DRV.value:
            metrics = build_metrics_timing_opt_drv(workspace, step)
        case StepEnum.TIMING_OPT_HOLD.value:
            metrics = build_metrics_timing_opt_hold(workspace, step)
        case StepEnum.LEGALIZATION.value:
            metrics = build_metrics_legalization(workspace, step)
        case StepEnum.ROUTING.value:
            metrics = build_metrics_routing(workspace, step)
        case StepEnum.DRC.value:
            metrics = build_metrics_drc(workspace, step)
        case StepEnum.FILLER.value:
            metrics = build_metrics_filler(workspace, step)
        case StepEnum.RCX.value:
            metrics = build_metrics_rcx(workspace, step)
        case StepEnum.STA.value:
            metrics = build_metrics_sta(workspace, step)
        case StepEnum.HARDEN.value:
            metrics = build_metrics_harden(workspace, step)
            
    if metrics is None:
        workspace.logger.info("\nno metrics - %s\n", step.name)
        return metrics
    
    info = {}        
    data = json_read(step.feature.get("db", ""))
    if data is not None:
        instance_num = data.get("Design Statis", {}).get("num_instances", 0) 
        info["instance"] = instance_num

        if metrics.data.get("Frequency [MHz]", 0) > 0:
            info["frequency"] = metrics.data.get("Frequency [MHz]", 0)   
    
    sub_flow.update_step(step_name=EccSubFlowEnum.analysis.value,
                         state=StateEnum.Invalid if metrics is None else StateEnum.Success,
                         info=info)
    
    
    workspace.logger.info("\nmetrics - \n%s", dict_to_str(metrics.data))
    return metrics


def build_metrics_timing(workspace: Workspace, 
                         step: WorkspaceStep) -> dict:
    metrics = {}
    
    data = json_read(step.feature.get('timing', ""))
    max_WNS = None
    if isinstance(data, dict) and len(data) > 0:
        for slack_item in data.get('slack', []):
            type = slack_item.get("delay_type", "")
            metrics[f"{type}_TNS"] = slack_item.get("TNS", 0)
            metrics[f"{type}_WNS"] = slack_item.get("WNS", 0)
            
            if type == "max":
                max_WNS = float(slack_item.get("WNS", 0))
            
    # frequency
    frequency = workspace.parameters.data.get("Frequency max [MHz]", 0)
    if frequency > 0 and max_WNS is not None:
        clk_period = 1000.0 / frequency
        
        real_frequency = 1000.0 / (clk_period - max_WNS) if max_WNS is not None else 0
        metrics["Frequency [MHz]"] = round(real_frequency, 2)

    return metrics

def build_metrics_db(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:
    # db summary matrics
    metrics = {}
    
    metrics['Tool'] = step.tool
    
    data = json_read(step.feature.get('db', ""))
    if isinstance(data, dict):
        layout = data.get('Design Layout', {})
        statistics = data.get('Design Statis', {})
        layout = layout if isinstance(layout, dict) else {}
        statistics = statistics if isinstance(statistics, dict) else {}

        for label, key, decimals in (
            ("Die area [μm^2]", "die_area", 3),
            ("Core area [μm^2]", "core_area", 3),
            ("Die width [um]", "die_bounding_width", None),
            ("Die height [um]", "die_bounding_height", None),
            ("Die util", "die_usage", 2),
            ("Core util", "core_usage", 2),
        ):
            value = _qor_number(layout.get(key))
            if value is None:
                continue
            if decimals is not None:
                value = round(value, decimals)
            metrics[label] = f"{value}"

        for label, key in (
            ("Total io pins", "num_iopins"),
            ("Total instances", "num_instances"),
            ("Total nets", "num_nets"),
        ):
            _add_number_metric(metrics, label, statistics.get(key))
        
    metrics.update(build_metrics_timing(workspace=workspace, step=step))

    return metrics

def build_metrics_floorplan(workspace: Workspace, 
                            step: WorkspaceStep) -> StepMetrics:
    """
    Build and return floorplan metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        # Add floorplan specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None

def build_metrics_net_opt(workspace: Workspace, 
                          step: WorkspaceStep) -> StepMetrics:
    """
    Build and return net operation metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    json_path = step.feature.get('step', "")
    db_data = json_read(step.feature.get('db', ""))
    pins = db_data.get("Pins", {}) if isinstance(db_data, dict) else {}
    fanout = pins.get("max_fanout") if isinstance(pins, dict) else None
    if fanout is None:
        fanout = workspace.parameters.data.get("Max fanout")
    _add_number_metric(metrics, "Max fanout", fanout)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_filler(workspace: Workspace, 
                         step: WorkspaceStep) -> StepMetrics:
    """
    Build and return filler metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        # Add filler specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_drc(workspace: Workspace, 
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build and return DRC metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if isinstance(data, dict):
        drc = data.get("drc", {})
        if isinstance(drc, dict):
            _add_number_metric(metrics, "drc_num", drc.get("number"))
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_routing(workspace: Workspace, 
                          step: WorkspaceStep) -> StepMetrics:
    """
    Build and return routing metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('db', "")
    data = json_read(json_path)
    if isinstance(data, dict):
        nets = data.get("Nets", {})
        if isinstance(nets, dict):
            _add_number_metric(metrics, "wire_len", nets.get("wire_len"))
            _add_number_metric(metrics, "num_via", nets.get("num_via"))

    route_data = json_read(step.feature.get('step', ""))
    if isinstance(route_data, dict):
        route = route_data.get("route", {})
        route = route if isinstance(route, dict) else {}
        la = route.get("LA", {})
        la = la if isinstance(la, dict) else {}
        _add_number_metric(
            metrics,
            "route_la_total_overflow",
            la.get("total_overflow"),
        )
        _add_number_metric(
            metrics,
            "route_la_total_demand",
            la.get("total_demand"),
        )

        dr = _latest_route_iteration(route.get("DR", []))
        if dr is not None:
            _add_number_metric(
                metrics,
                "route_dr_total_violation_count",
                dr.get("total_violation_num"),
            )
            _add_number_metric(
                metrics,
                "route_dr_total_patch_count",
                dr.get("total_patch_num"),
            )
            _add_number_metric(
                metrics,
                "route_dr_total_wirelength",
                dr.get("total_wire_length"),
            )
            _add_number_metric(
                metrics,
                "route_dr_total_via_count",
                dr.get("total_via_num"),
            )
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_rcx(workspace: Workspace,
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build RCX output completeness metrics.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))

    output_dir = step.output.get("dir", "")
    actual_spef_paths = _existing_files_in(output_dir, "*.spef")
    expected_spef_paths = [
        Path(spef_path)
        for spef_path in step.output.get("spef", [])
        if spef_path
    ]
    missing_spef_paths = [
        spef_path
        for spef_path in expected_spef_paths
        if not spef_path.is_file()
    ]

    metrics["rcx_spef_file_count"] = len(actual_spef_paths)
    metrics["rcx_expected_corner_count"] = (
        len(expected_spef_paths) if expected_spef_paths else len(actual_spef_paths)
    )
    metrics["rcx_missing_corner_count"] = len(missing_spef_paths)
    metrics["rcx_output_def_exists"] = _artifact_exists(
        step.output.get("def", ""),
        output_dir,
        "*_RCX.def.gz",
    )
    metrics["rcx_output_gds_exists"] = _artifact_exists(
        step.output.get("gds", ""),
        output_dir,
        "*.gds",
    )

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_sta(workspace: Workspace,
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build STA multi-corner timing summary metrics.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))

    output_dir = Path(step.output.get("dir", ""))
    qor_paths = sta_qor_summary_paths(workspace, output_dir)
    summaries = [
        summary
        for corner, report_path in qor_paths
        if (summary := read_sta_qor_summary(corner, report_path)) is not None
    ]
    setup_wns = None
    setup_tns = None
    setup_corner = ""
    setup_tns_corner = ""
    hold_wns = None
    hold_tns = None
    hold_corner = ""
    hold_tns_corner = ""
    frequency = None
    frequency_corner = ""
    setup_violation_count = 0
    hold_violation_count = 0

    for summary in summaries:
        if setup_wns is None or summary.setup_wns < setup_wns:
            setup_wns = summary.setup_wns
            setup_corner = summary.corner
        if setup_tns is None or summary.setup_tns < setup_tns:
            setup_tns = summary.setup_tns
            setup_tns_corner = summary.corner
        if hold_wns is None or summary.hold_wns < hold_wns:
            hold_wns = summary.hold_wns
            hold_corner = summary.corner
        if hold_tns is None or summary.hold_tns < hold_tns:
            hold_tns = summary.hold_tns
            hold_tns_corner = summary.corner
        if frequency is None or summary.frequency_mhz < frequency:
            frequency = summary.frequency_mhz
            frequency_corner = summary.corner
        setup_violation_count += summary.setup_nvp
        hold_violation_count += summary.hold_nvp

    _add_number_metric(metrics, "max_WNS", setup_wns)
    _add_number_metric(metrics, "max_TNS", setup_tns)
    _add_number_metric(metrics, "min_WNS", hold_wns)
    _add_number_metric(metrics, "min_TNS", hold_tns)
    _add_number_metric(metrics, "Frequency [MHz]", frequency)
    metrics["setup_violation_count"] = setup_violation_count
    metrics["hold_violation_count"] = hold_violation_count
    metrics["sta_corner_count"] = len(summaries)
    metrics["sta_expected_corner_count"] = len(qor_paths)
    metrics["sta_missing_corner_count"] = len(qor_paths) - len(summaries)
    metrics["sta_corner_scope"] = "all_configured_corners"
    if setup_corner:
        metrics["sta_worst_setup_corner"] = setup_corner
    if setup_tns_corner:
        metrics["sta_worst_setup_tns_corner"] = setup_tns_corner
    if hold_corner:
        metrics["sta_worst_hold_corner"] = hold_corner
    if hold_tns_corner:
        metrics["sta_worst_hold_tns_corner"] = hold_tns_corner
    if frequency_corner:
        metrics["sta_worst_frequency_corner"] = frequency_corner

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_harden(workspace: Workspace,
                         step: WorkspaceStep) -> StepMetrics:
    """
    Build final harden package completeness metrics.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))

    output_dir = step.output.get("dir", "")
    lib_check_path = (
        Path(f"{step.output.get('lib')}.check_sources.tsv")
        if step.output.get("lib", "")
        else None
    )
    artifact_checks = {
        "harden_gds_exists": _artifact_exists(step.output.get("gds", ""), output_dir, "*.gds"),
        "harden_lef_exists": _artifact_exists(step.output.get("lef", ""), output_dir, "*.lef"),
        "harden_lib_exists": _artifact_exists(step.output.get("lib", ""), output_dir, "*.lib"),
        "harden_lib_check_exists": _artifact_exists(
            lib_check_path,
            output_dir,
            "*.lib.check_sources.tsv",
        ),
        "harden_preview_exists": _artifact_exists(
            step.output.get("image", ""),
            output_dir,
            "*.png",
        ),
    }
    metrics.update(artifact_checks)
    metrics["harden_artifact_missing_count"] = sum(
        1 for exists in artifact_checks.values() if exists == 0
    )

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_legalization(workspace: Workspace, 
                               step: WorkspaceStep) -> StepMetrics:
    """
    Build and return legalization metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if isinstance(data, dict):
        legalization = data.get("legalization", {})
        if isinstance(legalization, dict):
            _add_number_metric(
                metrics,
                "total_movement",
                legalization.get("total_movement"),
            )
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_timing_opt_hold(workspace: Workspace, 
                                  step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (hold) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    # data = json_read(json_path)
    # if len(data) > 0:
    #     for clk_item in data.get("optHold", {}).get("clocks_timing", []):
    #         metrics["suggest_freq"] = clk_item.get("opt_suggest_freq", 0)
    #         metrics["hold_wns"] = clk_item.get("opt_wns", 0)
    #         metrics["hold_tns"] = clk_item.get("opt_tns", 0)
            
    #         break
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_timing_opt_drv(workspace: Workspace, 
                                 step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (driver) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    # data = json_read(json_path)
    # if len(data) > 0:
    #     for clk_item in data.get("optDrv", {}).get("clocks_timing", []):
    #         metrics["suggest_freq"] = clk_item.get("opt_suggest_freq", 0)
    #         metrics["wns"] = clk_item.get("opt_wns", 0)
    #         metrics["tns"] = clk_item.get("opt_tns", 0)
            
    #         break
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 

def build_metrics_cts(workspace: Workspace, 
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build and return CTS metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if isinstance(data, dict):
        cts = data.get("CTS", {})
        cts = cts if isinstance(cts, dict) else {}
        for metric, source_key in (
            ("buffer_num", "buffer_num"),
            ("buffer_area", "buffer_area"),
            ("clock_path_max_buffer", "clock_path_max_buffer"),
            ("clock_path_min_buffer", "clock_path_min_buffer"),
            ("total_clock_wirelength", "total_clock_wirelength"),
            ("max_clock_wirelength", "max_clock_wirelength"),
            ("max_level_of_clock_tree", "max_level_of_clock_tree"),
        ):
            _add_number_metric(metrics, metric, cts.get(source_key))
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_placement(workspace: Workspace, 
                            step: WorkspaceStep) -> StepMetrics:
    """
    Build and return placement metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if isinstance(data, dict):
        place = data.get("place", {})
        place = place if isinstance(place, dict) else {}
        _add_number_metric(metrics, "overflow", place.get("overflow"))
        _add_number_metric(metrics, "overflow_number", place.get("overflow_number"))
        _add_number_metric(metrics, "bin_number", place.get("bin_number"))
        gplace = place.get("gplace", {})
        dplace = place.get("dplace", {})
        if isinstance(gplace, dict):
            _add_number_metric(metrics, "GP HPWL", gplace.get("HPWL"), scale=0.001)
        if isinstance(dplace, dict):
            _add_number_metric(metrics, "DP HPWL", dplace.get("STWL"), scale=0.001)

    map_data = json_read(step.feature.get('map', ""))
    if isinstance(map_data, dict):
        wirelength = map_data.get("Wirelength", {})
        wirelength = wirelength if isinstance(wirelength, dict) else {}
        _add_number_metric(metrics, "HPWL", wirelength.get("HPWL"), scale=0.001)
        _add_number_metric(metrics, "GRWL", wirelength.get("GRWL"), scale=0.001)
        _add_number_metric(metrics, "FLUTE", wirelength.get("FLUTE"), scale=0.001)

        congestion = map_data.get("Congestion", {})
        congestion = congestion if isinstance(congestion, dict) else {}
        overflow = congestion.get("overflow", {})
        utilization = congestion.get("utilization", {})
        overflow = overflow if isinstance(overflow, dict) else {}
        utilization = utilization if isinstance(utilization, dict) else {}
        _add_number_metric(
            metrics,
            "place_congestion_egr_overflow_total",
            overflow.get("total", {}).get("union"),
        )
        _add_number_metric(
            metrics,
            "place_congestion_egr_overflow_max",
            overflow.get("max", {}).get("union"),
        )
        _add_number_metric(
            metrics,
            "place_rudy_utilization_max",
            utilization.get("rudy", {}).get("max", {}).get("union"),
        )
        _add_number_metric(
            metrics,
            "place_lutrudy_utilization_max",
            utilization.get("lutrudy", {}).get("max", {}).get("union"),
        )
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None
