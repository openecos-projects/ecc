#!/usr/bin/env python
import re
from csv import reader as csv_reader
from math import ceil, isfinite
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum, StepMetrics, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.sta_qor import (
    STA_QOR_SUMMARY_FILENAME,
    read_sta_qor_summary,
    read_sta_timing_paths,
    sta_qor_summary_paths,
    sta_timing_paths_paths,
    temperature_token,
)
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.utility import dict_to_str, json_read, json_write

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
    "cts_worst_optimized_skew_ns": {
        "name": "cts_worst_optimized_skew_ns",
        "display_name": "CTS Worst Optimized Skew Estimate",
        "unit": "ns",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
        "confidence": "medium",
    },
    "cts_worst_max_insertion_latency_ns": {
        "name": "cts_worst_max_insertion_latency_ns",
        "display_name": "CTS Worst Max Insertion Latency Estimate",
        "unit": "ns",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
        "confidence": "medium",
    },
    "cts_skew_target_unmet_count": {
        "name": "cts_skew_target_unmet_count",
        "display_name": "CTS Skew Target Unmet Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
        "confidence": "medium",
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
    "rcx_spef_parse_failure_count": {
        "name": "rcx_spef_parse_failure_count",
        "display_name": "RCX SPEF Parse Failure Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "rcx_worst_total_capacitance_ff": {
        "name": "rcx_worst_total_capacitance_ff",
        "display_name": "RCX Worst Total Capacitance",
        "unit": "fF",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "rcx_worst_coupling_capacitance_ff": {
        "name": "rcx_worst_coupling_capacitance_ff",
        "display_name": "RCX Worst Coupling Capacitance",
        "unit": "fF",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
    "rcx_worst_total_resistance_ohm": {
        "name": "rcx_worst_total_resistance_ohm",
        "display_name": "RCX Worst Total Resistance",
        "unit": "ohm",
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
    "harden_artifact_missing_count": {
        "name": "harden_artifact_missing_count",
        "display_name": "Harden Missing Artifact Count",
        "unit": "count",
        "dimension": "clock_robustness_dfm",
        "polarity": "lower_is_better",
    },
}

QOR_ANALYSIS_REVISION = "quality-gates-v4"

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
        "cts_worst_optimized_skew_ns",
        "cts_worst_max_insertion_latency_ns",
        "cts_skew_target_unmet_count",
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
        "rcx_spef_parse_failure_count",
        "rcx_worst_total_capacitance_ff",
        "rcx_worst_coupling_capacitance_ff",
        "rcx_worst_total_resistance_ohm",
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


def _route_layer_sort_key(layer: str) -> tuple[int, float | str, str]:
    layer_index = _qor_number(layer)
    if layer_index is None:
        return (1, layer, layer)
    return (0, float(layer_index), layer)


def _route_layer_metrics(route: dict, source_file) -> dict:
    la = route.get("LA", {})
    la = la if isinstance(la, dict) else {}
    dr = _latest_route_iteration(route.get("DR", []))
    dr = dr if isinstance(dr, dict) else {}

    la_maps = {
        "demand": la.get("routing_demand_map"),
        "overflow": la.get("routing_overflow_map"),
        "wirelength": la.get("routing_wire_length_map"),
        "via_count": la.get("cut_via_num_map"),
    }
    dr_maps = {
        "wirelength": dr.get("routing_wire_length_map"),
        "via_count": dr.get("cut_via_num_map"),
        "violation_count": dr.get("routing_violation_num_map"),
        "patch_count": dr.get("routing_patch_num_map"),
    }
    la_maps = {
        name: {str(layer): value for layer, value in values.items()}
        for name, values in la_maps.items()
        if isinstance(values, dict)
    }
    dr_maps = {
        name: {str(layer): value for layer, value in values.items()}
        for name, values in dr_maps.items()
        if isinstance(values, dict)
    }
    layers = sorted(
        {layer for values in (*la_maps.values(), *dr_maps.values()) for layer in values},
        key=_route_layer_sort_key,
    )

    records = []
    for layer in layers:
        record = {"layer": layer}
        layer_index = _qor_number(layer)
        if layer_index is not None:
            record["layer_index"] = layer_index

        la_record = {
            name: number
            for name, values in la_maps.items()
            if (number := _qor_number(values.get(layer))) is not None
        }
        if la_record:
            record["la"] = la_record

        dr_record = {
            name: number
            for name, values in dr_maps.items()
            if (number := _qor_number(values.get(layer))) is not None
        }
        if dr_record:
            record["dr"] = dr_record
        records.append(record)

    return {
        "schema_version": 1,
        "source_file": str(source_file),
        "final_dr_iteration": _qor_number(dr.get("iter")),
        "layers": records,
    }


def _map_csv_statistics(source_file) -> dict:
    path = Path(source_file) if source_file else None
    statistics = {
        "source_file": str(path) if path is not None else "",
        "available": path is not None and path.is_file(),
    }
    if not statistics["available"]:
        return statistics

    values = []
    row_count = 0
    column_count = 0
    try:
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv_reader(file):
                if not row:
                    continue
                row_count += 1
                column_count = max(column_count, len(row))
                values.extend(number for value in row if (number := _qor_number(value)) is not None)
    except (OSError, UnicodeDecodeError):
        statistics["available"] = False
        return statistics

    statistics.update(
        {
            "row_count": row_count,
            "column_count": column_count,
            "value_count": len(values),
        }
    )
    if not values:
        return statistics

    max_value = max(values)
    nonzero_count = sum(value != 0 for value in values)
    top_count = max(1, ceil(len(values) * 0.05))
    top_values = sorted(values, reverse=True)[:top_count]
    high_bin_threshold = max_value * 0.9
    high_bin_count = sum(value >= high_bin_threshold for value in values) if max_value > 0 else 0
    statistics.update(
        {
            "nonzero_count": nonzero_count,
            "nonzero_ratio": nonzero_count / len(values),
            "max": max_value,
            "top_5_percent_average": sum(top_values) / len(top_values),
            "high_bin_threshold": high_bin_threshold,
            "high_bin_count": high_bin_count,
            "high_bin_ratio": high_bin_count / len(values),
        }
    )
    return statistics


def _place_map_metrics(map_data: dict, source_file) -> dict:
    records = []
    congestion = map_data.get("Congestion", {})
    congestion = congestion if isinstance(congestion, dict) else {}
    congestion_maps = congestion.get("map", {})
    congestion_maps = congestion_maps if isinstance(congestion_maps, dict) else {}
    for metric, directions in sorted(congestion_maps.items()):
        if not isinstance(directions, dict):
            continue
        for direction, csv_path in sorted(directions.items()):
            if not isinstance(csv_path, (str, Path)) or not csv_path:
                continue
            records.append(
                {
                    "group": "congestion",
                    "metric": metric,
                    "direction": direction,
                    **_map_csv_statistics(csv_path),
                }
            )

    density = map_data.get("Density", {})
    density = density if isinstance(density, dict) else {}
    for group, maps in sorted(density.items()):
        if not isinstance(maps, dict):
            continue
        for metric, csv_path in sorted(maps.items()):
            if not isinstance(csv_path, (str, Path)) or not csv_path:
                continue
            records.append(
                {
                    "group": group,
                    "metric": metric,
                    **_map_csv_statistics(csv_path),
                }
            )

    return {
        "schema_version": 1,
        "source_file": str(source_file),
        "top_average_definition": "mean of the highest 5 percent of valid bins",
        "high_bin_definition": "valid bins at or above 90 percent of the map peak",
        "maps": records,
    }


def _sta_path_group_metrics(summaries, corner_contexts: dict[str, dict] | None = None) -> dict:
    corner_contexts = corner_contexts or {}
    records = []
    for summary in summaries:
        payload = json_read(summary.path)
        path_groups = payload.get("path_groups", []) if isinstance(payload, dict) else []
        if not isinstance(path_groups, list):
            continue
        for path_group in path_groups:
            if not isinstance(path_group, dict):
                continue
            name = path_group.get("name")
            if not isinstance(name, str) or not name:
                continue
            record = {
                "corner": summary.corner,
                "path_group": name,
                "source_file": str(summary.path),
            }
            context = corner_contexts.get(summary.corner)
            if isinstance(context, dict):
                record["corner_context"] = context
            for analysis_type, fields in (
                ("setup", ("wns", "tns", "nvp", "frequency_mhz")),
                ("hold", ("wns", "tns", "nvp")),
            ):
                analysis = path_group.get(analysis_type)
                analysis = analysis if isinstance(analysis, dict) else {}
                values = {
                    field: number
                    for field in fields
                    if (number := _qor_number(analysis.get(field))) is not None
                }
                if values:
                    record[analysis_type] = values
            records.append(record)

    records.sort(key=lambda record: (record["path_group"], record["corner"]))
    aggregates = []
    for name in sorted({record["path_group"] for record in records}):
        group_records = [record for record in records if record["path_group"] == name]
        aggregate = {
            "path_group": name,
            "corner_count": len(group_records),
        }
        for analysis_type, fields in (
            ("setup", ("wns", "tns", "frequency_mhz", "nvp")),
            ("hold", ("wns", "tns", "nvp")),
        ):
            analysis = {}
            for field in fields:
                values = [
                    (record, record.get(analysis_type, {}).get(field))
                    for record in group_records
                    if _qor_number(record.get(analysis_type, {}).get(field)) is not None
                ]
                if not values:
                    continue
                if field == "nvp":
                    analysis["nvp_total"] = sum(value for _, value in values)
                    continue
                worst_record, worst_value = min(values, key=lambda item: item[1])
                key = "minimum_frequency_mhz" if field == "frequency_mhz" else f"worst_{field}"
                analysis[key] = worst_value
                analysis[f"{key}_corner"] = worst_record["corner"]
            if analysis:
                aggregate[analysis_type] = analysis
        aggregates.append(aggregate)

    return {
        "schema_version": 1,
        "source_files": [str(summary.path) for summary in summaries],
        "records": records,
        "path_groups": aggregates,
    }


def _sta_timing_issue_source_file(step: WorkspaceStep, path: Path) -> str:
    try:
        return path.relative_to(step.directory).as_posix()
    except (TypeError, ValueError):
        return str(path)


def _sta_timing_artifact_paths_payload(step: WorkspaceStep, timing_artifacts) -> list[dict]:
    report_root = step.report.get("dir")
    artifact_paths = []
    for artifact in sorted(timing_artifacts, key=lambda artifact: artifact.corner):
        feature_dir = artifact.path.parent
        report_dir = Path(report_root) / artifact.corner if report_root else None
        artifact_paths.append(
            {
                "corner": artifact.corner,
                "report_dir": (
                    _sta_timing_issue_source_file(step, report_dir)
                    if report_dir is not None
                    else ""
                ),
                "feature_dir": _sta_timing_issue_source_file(step, feature_dir),
                "qor_summary_file": _sta_timing_issue_source_file(
                    step,
                    feature_dir / STA_QOR_SUMMARY_FILENAME,
                ),
                "timing_paths_file": _sta_timing_issue_source_file(step, artifact.path),
            }
        )
    return artifact_paths


def _sta_timing_issues_payload(
    workspace: Workspace,
    step: WorkspaceStep,
    timing_artifacts,
    expected_paths: list[tuple[str, Path]],
) -> dict:
    issues = []
    source_files = []
    for artifact in timing_artifacts:
        source_file = _sta_timing_issue_source_file(step, artifact.path)
        source_files.append(source_file)
        for timing_path in artifact.paths:
            slack = _qor_number(timing_path.get("slack_ns"))
            if slack is None or slack >= STA_TIMING_NEAR_FAIL_SLACK_NS:
                continue
            stages = [stage for stage in timing_path.get("stages", []) if isinstance(stage, dict)]
            dominant_stages = sorted(
                stages,
                key=lambda stage: (
                    -(_qor_number(stage.get("incremental_delay_ns")) or 0.0),
                    str(stage.get("pin", "")),
                ),
            )
            analysis_type = timing_path["analysis_type"]
            path_id = timing_path["path_id"]
            launch_clock_delay = _qor_number(timing_path.get("launch_clock_network_delay_ns"))
            capture_clock_delay = _qor_number(timing_path.get("capture_clock_network_delay_ns"))
            issues.append(
                {
                    "issue_id": f"sta_timing:{artifact.corner}:{analysis_type}:{path_id}",
                    "severity": "critical" if slack < 0 else "warning",
                    "corner": artifact.corner,
                    "analysis_type": analysis_type,
                    "path_group": timing_path["path_group"],
                    "start_point": timing_path["start_point"],
                    "end_point": timing_path["end_point"],
                    "launch_clock": timing_path["launch_clock"],
                    "capture_clock": timing_path["capture_clock"],
                    "check_type": timing_path["check_type"],
                    "slack_ns": slack,
                    "arrival_ns": _qor_number(timing_path.get("arrival_ns")),
                    "required_ns": _qor_number(timing_path.get("required_ns")),
                    "cppr_ns": _qor_number(timing_path.get("cppr_ns")),
                    "launch_clock_network_delay_ns": launch_clock_delay,
                    "capture_clock_network_delay_ns": capture_clock_delay,
                    "clock_network_delay_delta_ns": (
                        capture_clock_delay - launch_clock_delay
                        if launch_clock_delay is not None and capture_clock_delay is not None
                        else None
                    ),
                    "source_file": source_file,
                    "dominant_stages": dominant_stages,
                }
            )

    loaded_corners = {artifact.corner for artifact in timing_artifacts}
    missing_corners = sorted(corner for corner, _ in expected_paths if corner not in loaded_corners)
    issues.sort(
        key=lambda issue: (
            issue["slack_ns"],
            issue["corner"],
            issue["analysis_type"],
            issue["issue_id"],
        )
    )
    return {
        "schema_version": 1,
        "tool": "ecc",
        "step": StepEnum.STA.value,
        "design": workspace.design.name,
        "near_fail_slack_ns": STA_TIMING_NEAR_FAIL_SLACK_NS,
        "source_files": sorted(source_files),
        "artifact_paths": _sta_timing_artifact_paths_payload(step, timing_artifacts),
        "missing_corners": missing_corners,
        "issues": issues,
    }


def _save_sta_timing_issues(
    workspace: Workspace,
    step: WorkspaceStep,
    timing_artifacts,
    expected_paths: list[tuple[str, Path]],
) -> bool:
    output_path = step.analysis.get("sta_timing_issues")
    if output_path is None:
        return True
    return json_write(
        file_path=output_path,
        data=_sta_timing_issues_payload(
            workspace=workspace,
            step=step,
            timing_artifacts=timing_artifacts,
            expected_paths=expected_paths,
        ),
    )


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


_SPEF_CAPACITANCE_UNIT_TO_FF = {
    "F": 1.0e15,
    "MF": 1.0e12,
    "UF": 1.0e9,
    "NF": 1.0e6,
    "PF": 1.0e3,
    "FF": 1.0,
    "AF": 1.0e-3,
}
_SPEF_RESISTANCE_UNIT_TO_OHM = {
    "OHM": 1.0,
    "KOHM": 1.0e3,
    "MOHM": 1.0e6,
}


def _spef_unit_scale(tokens: list[str], units: dict[str, float]) -> float | None:
    if len(tokens) != 3:
        return None
    multiplier = _qor_number(tokens[1])
    unit_scale = units.get(tokens[2].upper())
    if multiplier is None or multiplier <= 0 or unit_scale is None:
        return None
    return float(multiplier) * unit_scale


def _spef_entry_value(tokens: list[str]) -> float | None:
    value = _qor_number(tokens[-1])
    if value is None or value < 0:
        return None
    return float(value)


def _read_spef_electrical_summary(spef_path: Path) -> dict | None:
    """Read bounded RC totals without retaining the SPEF's net-level content."""
    try:
        lines = spef_path.open(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError):
        return None

    has_header = False
    capacitance_scale = None
    resistance_scale = None
    section = ""
    net_count = 0
    ground_capacitance_ff = 0.0
    coupling_capacitance_ff = 0.0
    resistance_ohm = 0.0
    ground_capacitance_count = 0
    coupling_capacitance_count = 0
    resistance_count = 0

    try:
        with lines:
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue
                tokens = line.split()
                directive = tokens[0]
                if directive == "*SPEF":
                    has_header = True
                    section = ""
                    continue
                if directive == "*C_UNIT":
                    capacitance_scale = _spef_unit_scale(tokens, _SPEF_CAPACITANCE_UNIT_TO_FF)
                    continue
                if directive == "*R_UNIT":
                    resistance_scale = _spef_unit_scale(tokens, _SPEF_RESISTANCE_UNIT_TO_OHM)
                    continue
                if directive == "*D_NET":
                    if len(tokens) < 3 or _spef_entry_value(tokens) is None:
                        return None
                    net_count += 1
                    section = ""
                    continue
                if directive == "*CAP":
                    section = "cap"
                    continue
                if directive == "*RES":
                    section = "res"
                    continue
                if directive == "*END":
                    section = ""
                    continue
                if directive.startswith("*"):
                    continue

                if section == "cap":
                    if len(tokens) not in (3, 4):
                        return None
                    value = _spef_entry_value(tokens)
                    if value is None or capacitance_scale is None:
                        return None
                    if len(tokens) == 3:
                        ground_capacitance_ff += value * capacitance_scale
                        ground_capacitance_count += 1
                    else:
                        coupling_capacitance_ff += value * capacitance_scale
                        coupling_capacitance_count += 1
                elif section == "res":
                    if len(tokens) != 4:
                        return None
                    value = _spef_entry_value(tokens)
                    if value is None or resistance_scale is None:
                        return None
                    resistance_ohm += value * resistance_scale
                    resistance_count += 1
    except (OSError, UnicodeError):
        return None

    if not has_header or capacitance_scale is None or resistance_scale is None:
        return None

    return {
        "net_count": net_count,
        "ground_capacitance_count": ground_capacitance_count,
        "ground_capacitance_ff": round(ground_capacitance_ff, 6),
        "coupling_capacitance_count": coupling_capacitance_count,
        "coupling_capacitance_ff": round(coupling_capacitance_ff, 6),
        "total_capacitance_ff": round(ground_capacitance_ff + coupling_capacitance_ff, 6),
        "resistance_count": resistance_count,
        "total_resistance_ohm": round(resistance_ohm, 6),
    }


def _rcx_spef_corner_name(workspace: Workspace, spef_path: Path) -> str:
    design_name = workspace.design.top_module or workspace.design.name
    name = spef_path.stem
    prefix = f"{design_name}_" if design_name else ""
    return name[len(prefix) :] if prefix and name.startswith(prefix) else name


def _rcx_signoff_metrics(
    workspace: Workspace,
    actual_spef_paths: list[Path],
    expected_spef_paths: list[Path],
    missing_spef_paths: list[Path],
    corner_summaries: list[dict],
    parse_failures: list[dict],
) -> dict:
    expected_corners = [
        _rcx_spef_corner_name(workspace, spef_path) for spef_path in expected_spef_paths
    ]
    missing_corners = [
        _rcx_spef_corner_name(workspace, spef_path) for spef_path in missing_spef_paths
    ]
    summaries_by_corner = {
        summary["corner"]: summary
        for summary in corner_summaries
        if isinstance(summary.get("corner"), str)
    }
    failures_by_corner = {
        failure["corner"]: failure
        for failure in parse_failures
        if isinstance(failure.get("corner"), str)
    }
    all_corners = sorted(
        {
            *expected_corners,
            *(_rcx_spef_corner_name(workspace, path) for path in actual_spef_paths),
        }
    )
    rc_corners = []
    for corner in all_corners:
        summary = summaries_by_corner.get(corner)
        if corner in failures_by_corner:
            availability = "unparseable"
            reason = failures_by_corner[corner].get("reason")
        elif summary is not None:
            availability = "available"
            reason = None
        else:
            availability = "missing"
            reason = "missing_spef"
        rc_corners.append(
            {
                "rc_corner": corner,
                "label": corner,
                "availability": availability,
                "reason": reason,
                **(
                    {
                        "total_capacitance_ff": summary["total_capacitance_ff"],
                        "coupling_capacitance_ff": summary["coupling_capacitance_ff"],
                        "total_resistance_ohm": summary["total_resistance_ohm"],
                    }
                    if summary is not None
                    else {}
                ),
            }
        )

    configured_or_produced = bool(expected_spef_paths or actual_spef_paths)
    if not configured_or_produced:
        coverage_status = "unavailable"
    elif missing_corners or parse_failures:
        coverage_status = "incomplete"
    else:
        coverage_status = "pass"
    envelope_status = (
        "pass" if corner_summaries else "incomplete" if configured_or_produced else "unavailable"
    )
    return {
        "schema_version": 1,
        "coverage": {
            "status": coverage_status,
            "expected_count": (
                len(expected_spef_paths) if expected_spef_paths else len(actual_spef_paths)
            ),
            "available_count": len(corner_summaries),
            "missing_count": len(missing_corners),
            "unparseable_count": len(parse_failures),
            "missing_corners": missing_corners,
            "unparseable_corners": sorted(failures_by_corner),
        },
        "rc_corners": rc_corners,
        "parasitic_envelope": {
            "status": envelope_status,
            "worst_total_capacitance_ff": max(
                (summary["total_capacitance_ff"] for summary in corner_summaries),
                default=None,
            ),
            "worst_coupling_capacitance_ff": max(
                (summary["coupling_capacitance_ff"] for summary in corner_summaries),
                default=None,
            ),
            "worst_total_resistance_ohm": max(
                (summary["total_resistance_ohm"] for summary in corner_summaries),
                default=None,
            ),
        },
    }


def save_rcx_spef_feature_facts(workspace: Workspace, step: WorkspaceStep) -> bool:
    """Persist bounded RCX electrical summaries before QoR analysis reads them."""
    output_dir = step.output.get("dir", "")
    actual_spef_paths = _existing_files_in(output_dir, "*.spef")
    expected_spef_paths = [
        Path(spef_path) for spef_path in step.output.get("spef", []) if spef_path
    ]
    missing_spef_paths = [spef_path for spef_path in expected_spef_paths if not spef_path.is_file()]
    corner_summaries = []
    parse_failures = []
    for spef_path in actual_spef_paths:
        summary = _read_spef_electrical_summary(spef_path)
        corner = _rcx_spef_corner_name(workspace, spef_path)
        if summary is None:
            parse_failures.append({"corner": corner, "reason": "invalid_spef"})
            continue
        corner_summaries.append({"corner": corner, **summary})

    total_capacitances = [summary["total_capacitance_ff"] for summary in corner_summaries]
    coupling_capacitances = [summary["coupling_capacitance_ff"] for summary in corner_summaries]
    total_resistances = [summary["total_resistance_ohm"] for summary in corner_summaries]
    facts = {
        "spef_file_count": len(actual_spef_paths),
        "expected_corner_count": (
            len(expected_spef_paths) if expected_spef_paths else len(actual_spef_paths)
        ),
        "missing_corner_count": len(missing_spef_paths),
        "output_def_exists": _artifact_exists(
            step.output.get("def", ""), output_dir, "*_RCX.def.gz"
        ),
        "output_gds_exists": _artifact_exists(step.output.get("gds", ""), output_dir, "*.gds"),
        "electrical_summary": {
            "schema_version": 1,
            "parsed_corner_count": len(corner_summaries),
            "parse_failure_count": len(parse_failures),
            "corners": corner_summaries,
            "parse_failures": parse_failures,
            "worst_total_capacitance_ff": max(total_capacitances, default=None),
            "worst_coupling_capacitance_ff": max(coupling_capacitances, default=None),
            "worst_total_resistance_ohm": max(total_resistances, default=None),
        },
        "signoff_metrics": _rcx_signoff_metrics(
            workspace=workspace,
            actual_spef_paths=actual_spef_paths,
            expected_spef_paths=expected_spef_paths,
            missing_spef_paths=missing_spef_paths,
            corner_summaries=corner_summaries,
            parse_failures=parse_failures,
        ),
    }
    return _save_step_feature_facts(step, "rcx", facts)


def save_cts_timing_feature_facts(step: WorkspaceStep, timing_quality: dict) -> bool:
    """Merge iCTS post-optimization FastSTA timing facts into CTS feature data."""
    if not isinstance(timing_quality, dict):
        return False
    feature_path = step.feature.get("step")
    feature = json_read(feature_path)
    cts = feature.get("CTS") if isinstance(feature, dict) else None
    cts = cts if isinstance(cts, dict) else {}
    return _save_step_feature_facts(
        step,
        "CTS",
        {**cts, "timing_quality": timing_quality},
    )


def _save_step_feature_facts(step: WorkspaceStep, key: str, facts: dict) -> bool:
    feature_path = step.feature.get("step")
    if feature_path is None:
        return False
    existing = json_read(feature_path)
    payload = existing if isinstance(existing, dict) else {}
    payload[key] = facts
    return json_write(file_path=feature_path, data=payload)


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
STA_TIMING_NEAR_FAIL_SLACK_NS = 0.05
_PROCESS_CORNER_PATTERN = re.compile(r"(?:^|[_./-])(tt|ss|ff|sf|fs)(?=[_./-]|$)", re.IGNORECASE)
_VOLTAGE_PATTERN = re.compile(r"(?:^|[_./-])(\d+p\d+)(?=[_./-]|$)", re.IGNORECASE)


def _liberty_process_corner(paths) -> str:
    corners = {
        match.group(1).upper()
        for path in paths
        if isinstance(path, str)
        for match in [_PROCESS_CORNER_PATTERN.search(path)]
        if match is not None
    }
    if len(corners) == 1:
        return next(iter(corners))
    return "mixed" if corners else "unknown"


def _liberty_voltage(paths) -> float | None:
    voltages = {
        float(match.group(1).lower().replace("p", "."))
        for path in paths
        if isinstance(path, str)
        for match in [_VOLTAGE_PATTERN.search(path)]
        if match is not None
    }
    return next(iter(voltages)) if len(voltages) == 1 else None


def _format_signoff_corner_label(
    configured_role: str,
    process_corner: str,
    voltage_v: float | None,
    temperature_c,
    rc_corner: str,
) -> str:
    voltage = f"{voltage_v:g} V" if voltage_v is not None else "voltage unknown"
    temperature = _qor_number(temperature_c)
    temperature_text = f"{temperature:g} C" if temperature is not None else "temperature unknown"
    return " - ".join(
        (
            configured_role,
            process_corner,
            voltage,
            temperature_text,
            rc_corner,
        )
    )


def _sta_group_status(coverage_status: str, first_value, second_value, violation_count) -> str:
    if first_value is None or second_value is None or violation_count is None:
        return "unavailable" if coverage_status == "unavailable" else "incomplete"
    if first_value < 0 or second_value < 0 or violation_count > 0:
        return "blocked"
    return "pass" if coverage_status == "pass" else "incomplete"


def _sta_frequency_status(coverage_status: str, frequency) -> str:
    if frequency is None:
        return "unavailable" if coverage_status == "unavailable" else "incomplete"
    return "pass" if coverage_status == "pass" else "incomplete"


def _sta_signoff_metrics(
    workspace: Workspace,
    step: WorkspaceStep,
    qor_paths: list[tuple[str, Path]],
    summaries,
    setup_wns,
    setup_corner: str,
    setup_tns,
    setup_tns_corner: str,
    setup_violation_count,
    hold_wns,
    hold_corner: str,
    hold_tns,
    hold_tns_corner: str,
    hold_violation_count,
    frequency,
    frequency_corner: str,
) -> dict:
    sta_data = json_read(workspace.config.get(StepEnum.STA.value, ""))
    sta_data = sta_data if isinstance(sta_data, dict) else {}
    liberty_by_role = {
        liberty.get("corner"): liberty
        for liberty in sta_data.get("liberty", [])
        if isinstance(liberty, dict) and isinstance(liberty.get("corner"), str)
    }
    expected_paths_by_corner = dict(qor_paths)
    summaries_by_corner = {summary.corner: summary for summary in summaries}
    corners = []
    for signoff_group in sta_data.get("signoff", []):
        if not isinstance(signoff_group, dict):
            continue
        for configured_role, rc_corners in signoff_group.items():
            liberty = liberty_by_role.get(configured_role)
            if liberty is None:
                continue
            if isinstance(rc_corners, str):
                rc_corners = [rc_corners]
            if not isinstance(rc_corners, list):
                continue
            temperature_c = _qor_number(liberty.get("temperature"))
            liberty_paths = liberty.get("path", [])
            if isinstance(liberty_paths, str):
                liberty_paths = [liberty_paths]
            liberty_paths = liberty_paths if isinstance(liberty_paths, list) else []
            process_corner = _liberty_process_corner(liberty_paths)
            voltage_v = _liberty_voltage(liberty_paths)
            for rc_corner in rc_corners:
                if not isinstance(rc_corner, str) or not rc_corner:
                    continue
                sta_corner = (
                    f"{configured_role}_{temperature_token(liberty.get('temperature'))}/{rc_corner}"
                )
                expected_path = expected_paths_by_corner.get(sta_corner)
                summary = summaries_by_corner.get(sta_corner)
                if summary is not None:
                    availability = "available"
                    reason = None
                elif expected_path is not None and expected_path.is_file():
                    availability = "unparseable"
                    reason = "invalid_qor_summary"
                else:
                    availability = "missing"
                    reason = "missing_qor_summary"
                corners.append(
                    {
                        "sta_corner": sta_corner,
                        "configured_role": configured_role,
                        "process_corner": process_corner,
                        "voltage_v": voltage_v,
                        "temperature_c": temperature_c,
                        "rc_corner": rc_corner,
                        "label": _format_signoff_corner_label(
                            configured_role,
                            process_corner,
                            voltage_v,
                            temperature_c,
                            rc_corner,
                        ),
                        "availability": availability,
                        "reason": reason,
                        "summary_file": _relative_step_path(step, expected_path),
                    }
                )

    available_corners = [corner for corner in corners if corner["availability"] == "available"]
    missing_corners = [
        corner["sta_corner"] for corner in corners if corner["availability"] == "missing"
    ]
    unparseable_corners = [
        corner["sta_corner"] for corner in corners if corner["availability"] == "unparseable"
    ]
    if not corners:
        coverage_status = "unavailable"
    elif missing_corners or unparseable_corners:
        coverage_status = "incomplete"
    else:
        coverage_status = "pass"

    setup_status = _sta_group_status(coverage_status, setup_wns, setup_tns, setup_violation_count)
    hold_status = _sta_group_status(coverage_status, hold_wns, hold_tns, hold_violation_count)
    frequency_status = _sta_frequency_status(coverage_status, frequency)
    return {
        "schema_version": 1,
        "coverage": {
            "status": coverage_status,
            "expected_count": len(corners),
            "available_count": len(available_corners),
            "missing_count": len(missing_corners),
            "unparseable_count": len(unparseable_corners),
            "missing_corners": missing_corners,
            "unparseable_corners": unparseable_corners,
        },
        "corners": corners,
        "setup": {
            "status": setup_status,
            "worst_wns_ns": setup_wns,
            "worst_wns_corner": setup_corner or None,
            "worst_tns_ns": setup_tns,
            "worst_tns_corner": setup_tns_corner or None,
            "violation_count": setup_violation_count,
        },
        "hold": {
            "status": hold_status,
            "worst_wns_ns": hold_wns,
            "worst_wns_corner": hold_corner or None,
            "worst_tns_ns": hold_tns,
            "worst_tns_corner": hold_tns_corner or None,
            "violation_count": hold_violation_count,
        },
        "frequency": {
            "status": frequency_status,
            "minimum_mhz": frequency,
            "corner": frequency_corner or None,
        },
    }


def _sta_qor_record_corner(step_metrics: StepMetrics, legacy_name: str) -> str | None:
    corner_key = STA_QOR_CORNER_FIELDS.get(legacy_name)
    if corner_key is None:
        return None

    corner = step_metrics.data.get(corner_key)
    return corner if isinstance(corner, str) and corner else None


def _sta_qor_source_file(step: WorkspaceStep) -> str | None:
    feature_dir = step.feature.get("dir")
    if feature_dir is None or feature_dir == "":
        return None
    return str(Path(feature_dir) / "**" / STA_QOR_SUMMARY_FILENAME)


def _relative_step_path(step: WorkspaceStep, path) -> str | None:
    if path is None or path == "":
        return None
    try:
        candidate = Path(path)
        return candidate.relative_to(step.directory).as_posix()
    except (TypeError, ValueError):
        return None


def _is_feature_source(source) -> bool:
    if not isinstance(source, dict) or source.get("kind") != "feature":
        return False
    path = source.get("path")
    selector = source.get("selector")
    return (
        isinstance(path, str)
        and path.startswith("feature/")
        and ".." not in Path(path).parts
        and isinstance(selector, str)
        and (selector == "" or selector.startswith("/"))
    )


def _normalise_feature_paths(step: WorkspaceStep, value):
    if isinstance(value, Path):
        return _relative_step_path(step, value) or ""
    if isinstance(value, list):
        return [_normalise_feature_paths(step, item) for item in value]
    if isinstance(value, dict):
        normalised = {}
        for key, item in value.items():
            if key in {"source_file", "feature_source", "source_files"}:
                if isinstance(item, list):
                    normalised[key] = [_relative_step_path(step, path) or "" for path in item]
                else:
                    normalised[key] = _relative_step_path(step, item) or ""
            else:
                normalised[key] = _normalise_feature_paths(step, item)
        return normalised
    return value


def _metric_scope_and_roles(step: WorkspaceStep, metric_id: str) -> tuple[str, str, str]:
    scope = step.name.lower().replace(" ", "_")
    project_role = "trend"
    step_role = "secondary"

    if step.name == StepEnum.SYNTHESIS.value:
        scope = "synthesis"
        step_role = "primary"
    elif step.name == StepEnum.FLOORPLAN.value:
        scope = "floorplan"
        step_role = "primary"
    elif step.name == StepEnum.NETLIST_OPT.value:
        scope = "fanout_repair"
        step_role = "primary" if metric_id == "fanout_max" else "secondary"
    elif step.name == StepEnum.PLACEMENT.value:
        scope = "placement"
        step_role = "primary" if metric_id.startswith("place_") else "secondary"
    elif step.name == StepEnum.CTS.value:
        scope = "cts"
        step_role = (
            "primary"
            if metric_id.startswith("cts_") or metric_id == "clock_wirelength"
            else "secondary"
        )
    elif step.name == StepEnum.LEGALIZATION.value:
        scope = "legalization"
        step_role = "primary"
    elif step.name == StepEnum.ROUTING.value:
        scope = "final_route"
        project_role = "final"
        step_role = "primary"
    elif step.name == StepEnum.DRC.value:
        scope = "final_drc"
        project_role = "gate" if metric_id == "drc_count" else "final"
        step_role = "primary"
    elif step.name == StepEnum.RCX.value:
        scope = "signoff_rcx"
        project_role = "gate" if metric_id == "rcx_missing_corner_count" else "final"
        step_role = "primary"
    elif step.name == StepEnum.STA.value:
        scope = "all_configured_corners"
        project_role = (
            "gate"
            if metric_id
            in {
                "sta_setup_wns",
                "sta_setup_tns",
                "sta_hold_wns",
                "sta_hold_tns",
                "sta_setup_violation_count",
                "sta_hold_violation_count",
                "sta_missing_corner_count",
            }
            else "final"
        )
        step_role = "primary"
    elif step.name == StepEnum.HARDEN.value:
        scope = "final_delivery"
        project_role = "final"
        step_role = "primary"

    return scope, project_role, step_role


def _metric_analysis_group_and_rating(
    step: WorkspaceStep, metric_id: str, project_role: str, direction: str
) -> tuple[str, dict]:
    rating = {
        "gate": project_role == "gate",
        "score": direction != "trend_only",
        "trend": True,
    }
    group = f"{step.name.lower()}_metrics"
    if metric_id in {"runtime_seconds", "peak_memory_mb"}:
        return "runtime", {"gate": False, "score": False, "trend": True}
    if step.name == StepEnum.RCX.value:
        if metric_id in {"rcx_output_def_exists", "rcx_output_gds_exists"}:
            return "rcx_output_artifacts", {
                "gate": False,
                "score": False,
                "trend": True,
            }
        if metric_id in {
            "rcx_spef_file_count",
            "rcx_expected_corner_count",
            "rcx_missing_corner_count",
        }:
            return "rcx_corner_coverage", {"gate": True, "score": False, "trend": True}
        if metric_id == "rcx_spef_parse_failure_count":
            return "rcx_parse_health", {"gate": True, "score": False, "trend": True}
        if metric_id.startswith("rcx_worst_"):
            return "rcx_parasitic_envelope", {
                "gate": False,
                "score": False,
                "trend": True,
            }
    if step.name == StepEnum.STA.value:
        if metric_id in {
            "sta_corner_count",
            "sta_expected_corner_count",
            "sta_missing_corner_count",
        }:
            return "sta_signoff_coverage", {"gate": True, "score": False, "trend": True}
        if metric_id in {
            "sta_setup_wns",
            "sta_setup_tns",
            "sta_setup_violation_count",
        }:
            return "sta_setup_closure", {"gate": True, "score": True, "trend": True}
        if metric_id in {
            "sta_hold_wns",
            "sta_hold_tns",
            "sta_hold_violation_count",
        }:
            return "sta_hold_closure", {"gate": True, "score": True, "trend": True}
        if metric_id == "sta_frequency_mhz":
            return "sta_frequency_margin", {"gate": False, "score": True, "trend": True}
    return group, rating


def _sta_corner_context(step: WorkspaceStep, corner: str | None) -> dict | None:
    if step.name != StepEnum.STA.value or not corner:
        return None
    feature = json_read(step.feature.get("step", ""))
    sta = feature.get("sta") if isinstance(feature, dict) else None
    signoff_metrics = sta.get("signoff_metrics") if isinstance(sta, dict) else None
    corners = signoff_metrics.get("corners") if isinstance(signoff_metrics, dict) else None
    if not isinstance(corners, list):
        return None
    for item in corners:
        if isinstance(item, dict) and item.get("sta_corner") == corner:
            return {
                key: item.get(key)
                for key in (
                    "configured_role",
                    "process_corner",
                    "voltage_v",
                    "temperature_c",
                    "rc_corner",
                    "label",
                )
            }
    return None


_DB_FEATURE_SELECTORS = {
    "die_area": "/Design Layout/die_area",
    "core_area": "/Design Layout/core_area",
    "die_width": "/Design Layout/die_bounding_width",
    "die_height": "/Design Layout/die_bounding_height",
    "die_utilization": "/Design Layout/die_usage",
    "core_utilization": "/Design Layout/core_usage",
    "io_pin_count": "/Design Statis/num_iopins",
    "instance_count": "/Design Statis/num_instances",
    "net_count": "/Design Statis/num_nets",
}


_STA_FEATURE_SELECTORS = {
    "sta_setup_wns": "/summary/setup/wns",
    "sta_setup_tns": "/summary/setup/tns",
    "sta_hold_wns": "/summary/hold/wns",
    "sta_hold_tns": "/summary/hold/tns",
    "sta_frequency_mhz": "/summary/setup/frequency_mhz",
}

_STA_AGGREGATE_FEATURE_SELECTORS = {
    "sta_corner_count": "/sta/signoff_metrics/coverage/available_count",
    "sta_expected_corner_count": "/sta/signoff_metrics/coverage/expected_count",
    "sta_missing_corner_count": "/sta/signoff_metrics/coverage/missing_count",
    "sta_setup_violation_count": "/sta/signoff_metrics/setup/violation_count",
    "sta_hold_violation_count": "/sta/signoff_metrics/hold/violation_count",
}

_RUN_FEATURE_METRICS = (
    ("runtime_seconds", "Step Runtime", "s", "/run/runtime_seconds"),
    ("peak_memory_mb", "Peak Memory", "MB", "/run/peak_memory_mb"),
)


def _run_feature_qor_records(step: WorkspaceStep) -> list[dict]:
    feature_path = step.feature.get("step")
    source_path = _relative_step_path(step, feature_path)
    if source_path is None:
        return []

    feature = json_read(feature_path)
    run = feature.get("run") if isinstance(feature, dict) else None
    if not isinstance(run, dict):
        return []

    records = []
    for metric_id, display_name, unit, selector in _RUN_FEATURE_METRICS:
        value = _qor_number(run.get(metric_id))
        if value is None or value < 0:
            continue
        records.append(
            {
                "id": metric_id,
                "display_name": display_name,
                "value": value,
                "unit": unit,
                "category": "runtime",
                "direction": "lower_is_better",
                "scope": f"{step.name.lower()}_execution",
                "corner": None,
                "project_role": "trend",
                "step_role": "secondary",
                "analysis_group": "runtime",
                "rating": {"gate": False, "score": False, "trend": True},
                "confidence": "high",
                "source": {
                    "kind": "feature",
                    "path": source_path,
                    "selector": selector,
                },
            }
        )
    return records


def _timing_constraint_context(step: WorkspaceStep) -> dict | None:
    feature_path = step.feature.get("step")
    source_path = _relative_step_path(step, feature_path)
    if source_path is None:
        return None

    feature = json_read(feature_path)
    constraints = feature.get("constraints") if isinstance(feature, dict) else None
    sdc = constraints.get("sdc") if isinstance(constraints, dict) else None
    if not isinstance(sdc, dict) or sdc.get("availability") != "available":
        return None

    digest = sdc.get("sha256")
    size_bytes = _qor_number(sdc.get("size_bytes"))
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or size_bytes is None
        or size_bytes < 0
        or size_bytes != int(size_bytes)
    ):
        return None
    try:
        int(digest, 16)
    except ValueError:
        return None

    return {
        "sdc_sha256": digest.lower(),
        "sdc_size_bytes": int(size_bytes),
        "source": {
            "kind": "feature",
            "path": source_path,
            "selector": "/constraints/sdc",
        },
    }


def _metric_feature_source(
    step: WorkspaceStep, metric_id: str, corner: str | None = None
) -> dict | None:
    feature_path = None
    selector = ""

    if metric_id.startswith("synthesis_"):
        feature_path = step.feature.get("stat")
        selector = {
            "synthesis_cell_area": "/design/area",
            "synthesis_cell_count": "/design/num_cells",
            "synthesis_wire_count": "/design/num_wires",
            "synthesis_port_count": "/design/num_port_bits",
        }.get(metric_id, "")
    elif metric_id in _DB_FEATURE_SELECTORS:
        feature_path = step.feature.get("db")
        selector = _DB_FEATURE_SELECTORS[metric_id]
    elif metric_id == "fanout_max":
        feature_path = step.feature.get("db")
        selector = "/Pins/max_fanout"
    elif metric_id.startswith("place_"):
        feature_path = (
            step.feature.get("map")
            if metric_id
            in {
                "place_hpwl",
                "place_grwl",
                "place_flute_wirelength",
                "place_congestion_egr_overflow_total",
                "place_congestion_egr_overflow_max",
                "place_rudy_utilization_max",
                "place_lutrudy_utilization_max",
            }
            else step.feature.get("step")
        )
        selector = {
            "place_hpwl": "/Wirelength/HPWL",
            "place_grwl": "/Wirelength/GRWL",
            "place_flute_wirelength": "/Wirelength/FLUTE",
            "place_congestion_egr_overflow_total": ("/Congestion/overflow/total/union"),
            "place_congestion_egr_overflow_max": ("/Congestion/overflow/max/union"),
            "place_rudy_utilization_max": ("/Congestion/utilization/rudy/max/union"),
            "place_lutrudy_utilization_max": ("/Congestion/utilization/lutrudy/max/union"),
        }.get(metric_id, "")
    elif metric_id.startswith("cts_") or metric_id in {
        "clock_wirelength",
        "clock_path_max_buffer",
        "clock_path_min_buffer",
    }:
        feature_path = step.feature.get("step")
        selector = {
            "clock_path_max_buffer": "/CTS/clock_path_max_buffer",
            "clock_path_min_buffer": "/CTS/clock_path_min_buffer",
            "cts_buffer_count": "/CTS/buffer_num",
            "cts_buffer_area": "/CTS/buffer_area",
            "clock_wirelength": "/CTS/total_clock_wirelength",
            "cts_clock_wirelength_max": "/CTS/max_clock_wirelength",
            "cts_clock_tree_max_level": "/CTS/max_level_of_clock_tree",
            "cts_worst_optimized_skew_ns": ("/CTS/timing_quality/worst_optimized_skew_ns"),
            "cts_worst_max_insertion_latency_ns": (
                "/CTS/timing_quality/worst_max_insertion_latency_ns"
            ),
            "cts_skew_target_unmet_count": ("/CTS/timing_quality/target_unmet_count"),
        }.get(metric_id, "")
    elif metric_id in {"route_wirelength", "route_via_count"}:
        feature_path = step.feature.get("db")
        selector = {
            "route_wirelength": "/Nets/wire_len",
            "route_via_count": "/Nets/num_via",
        }.get(metric_id, "")
    elif metric_id.startswith("route_") or metric_id == "drc_count":
        feature_path = step.feature.get("step")
        selector = {
            "drc_count": "/drc/number",
            "route_dr_total_violation_count": "/route/DR",
            "route_dr_total_patch_count": "/route/DR",
            "route_dr_total_wirelength": "/route/DR",
            "route_dr_total_via_count": "/route/DR",
            "route_la_total_overflow": "/route/LA",
            "route_la_total_demand": "/route/LA",
        }.get(metric_id, "")
    elif metric_id.startswith("rcx_") or metric_id.startswith("harden_"):
        feature_path = step.feature.get("step")
        selector = {
            "rcx_spef_file_count": "/rcx/spef_file_count",
            "rcx_expected_corner_count": "/rcx/expected_corner_count",
            "rcx_missing_corner_count": "/rcx/signoff_metrics/coverage/missing_count",
            "rcx_spef_parse_failure_count": ("/rcx/signoff_metrics/coverage/unparseable_count"),
            "rcx_worst_total_capacitance_ff": (
                "/rcx/signoff_metrics/parasitic_envelope/worst_total_capacitance_ff"
            ),
            "rcx_worst_coupling_capacitance_ff": (
                "/rcx/signoff_metrics/parasitic_envelope/worst_coupling_capacitance_ff"
            ),
            "rcx_worst_total_resistance_ohm": (
                "/rcx/signoff_metrics/parasitic_envelope/worst_total_resistance_ohm"
            ),
            "rcx_output_def_exists": "/rcx/output_def_exists",
            "rcx_output_gds_exists": "/rcx/output_gds_exists",
            "harden_gds_exists": "/harden/artifacts/harden_gds_exists",
            "harden_lef_exists": "/harden/artifacts/harden_lef_exists",
            "harden_lib_exists": "/harden/artifacts/harden_lib_exists",
            "harden_artifact_missing_count": "/harden/artifact_missing_count",
        }.get(metric_id, "")
    elif metric_id in _STA_FEATURE_SELECTORS:
        feature_dir = step.feature.get("dir")
        if feature_dir and corner:
            feature_path = Path(feature_dir) / corner / STA_QOR_SUMMARY_FILENAME
        selector = _STA_FEATURE_SELECTORS.get(metric_id, "")
    elif metric_id in _STA_AGGREGATE_FEATURE_SELECTORS:
        feature_path = step.feature.get("step")
        selector = _STA_AGGREGATE_FEATURE_SELECTORS[metric_id]

    path = _relative_step_path(step, feature_path)
    if path is None:
        return None
    return {
        "kind": "feature",
        "path": path,
        "selector": selector,
    }


def _qor_detail_records(step: WorkspaceStep, step_metrics: StepMetrics) -> list[dict]:
    details = []
    detail_specs = (
        ("place_map_metrics", "place_map_summary", step.feature.get("map")),
        ("cts_clock_skew_metrics", "cts_clock_skew_table", step.feature.get("step")),
        ("route_layer_metrics", "layer_table", step.feature.get("step")),
        ("rcx_electrical_corner_metrics", "rcx_spef_corner_table", step.feature.get("step")),
        ("sta_path_group_metrics", "path_group_table", step.feature.get("dir")),
    )
    for detail_id, presentation, feature_path in detail_specs:
        summary = step_metrics.data.get(detail_id)
        if not isinstance(summary, dict):
            continue
        if detail_id == "sta_path_group_metrics":
            source_files = summary.get("source_files")
            if not isinstance(source_files, list) or not source_files:
                continue
            feature_path = source_files[0]
        source_path = _relative_step_path(step, feature_path)
        if source_path is None:
            continue
        details.append(
            {
                "id": detail_id,
                "presentation": presentation,
                "summary": _normalise_feature_paths(step, summary),
                "feature_source": {
                    "kind": "feature",
                    "path": source_path,
                    "selector": (
                        "/CTS/timing_quality"
                        if detail_id == "cts_clock_skew_metrics"
                        else "/rcx/signoff_metrics"
                        if detail_id == "rcx_electrical_corner_metrics"
                        else ""
                    ),
                },
            }
        )
    if step.name == StepEnum.DRC.value:
        feature_path = step.feature.get("step")
        source_path = _relative_step_path(step, feature_path)
        if source_path is not None:
            rule_layers = [
                {
                    "metric_id": record["metric_id"],
                    "display_name": record["display_name"],
                    "value": record["value"],
                    "unit": record["unit"],
                }
                for record in _drc_rule_layer_hotspot_records(step)
            ]
            details.append(
                {
                    "id": "drc_rule_layer_summary",
                    "presentation": "rule_layer_table",
                    "summary": {"top_violations": rule_layers},
                    "feature_source": {
                        "kind": "feature",
                        "path": source_path,
                        "selector": "/drc/distribution",
                    },
                }
            )
    return details


def build_qor_metrics_payload(
    workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics
) -> dict:
    records = []
    invalid_metric_source_ids = []
    for legacy_name, raw_value in step_metrics.data.items():
        mapping = QOR_METRIC_MAP.get(legacy_name)
        if mapping is None:
            continue

        value = _qor_number(raw_value)
        if value is None:
            continue

        metric_id = mapping["name"]
        corner = _sta_qor_record_corner(step_metrics, legacy_name)
        scope, project_role, step_role = _metric_scope_and_roles(step, metric_id)
        analysis_group, rating = _metric_analysis_group_and_rating(
            step, metric_id, project_role, mapping["polarity"]
        )
        if step.name == StepEnum.STA.value and corner is not None:
            scope = "all_configured_corners"
        record = {
            "id": metric_id,
            "display_name": mapping["display_name"],
            "value": value,
            "unit": mapping["unit"],
            "category": mapping["dimension"],
            "direction": mapping["polarity"],
            "scope": scope,
            "corner": corner,
            "project_role": project_role,
            "step_role": step_role,
            "analysis_group": analysis_group,
            "rating": rating,
            "confidence": mapping.get("confidence", "high"),
        }
        corner_context = _sta_corner_context(step, corner)
        if corner_context is not None:
            record["corner_context"] = corner_context
        source = _metric_feature_source(step, metric_id, corner=corner)
        if not _is_feature_source(source):
            invalid_metric_source_ids.append(metric_id)
            continue
        record["source"] = source
        records.append(record)

    for record in _run_feature_qor_records(step):
        if _is_feature_source(record.get("source")):
            records.append(record)
        else:
            invalid_metric_source_ids.append(record["id"])
    records.sort(key=lambda record: record["id"])
    details = []
    invalid_detail_ids = []
    for detail in _qor_detail_records(step, step_metrics):
        if _is_feature_source(detail.get("feature_source")):
            details.append(detail)
        else:
            invalid_detail_ids.append(detail["id"])
    timing_constraints = _timing_constraint_context(step)
    sources = []
    seen_sources = set()
    source_records = [*records, *details]
    if timing_constraints is not None and _is_feature_source(timing_constraints["source"]):
        source_records.append({"source": timing_constraints["source"]})
    for record in source_records:
        source = record.get("source", record.get("feature_source"))
        if not isinstance(source, dict):
            continue
        key = (source.get("kind"), source.get("path"))
        if not isinstance(key[1], str) or not key[1] or key in seen_sources:
            continue
        seen_sources.add(key)
        sources.append({"kind": key[0], "path": key[1]})

    payload = {
        "schema_version": 3,
        "analysis_revision": QOR_ANALYSIS_REVISION,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "status": "success",
        "metrics": records,
        "details": details,
        "sources": sources,
        "integrity": {
            "status": (
                "pass" if not invalid_metric_source_ids and not invalid_detail_ids else "incomplete"
            ),
            "invalid_metric_source_ids": sorted(set(invalid_metric_source_ids)),
            "invalid_detail_ids": sorted(set(invalid_detail_ids)),
        },
    }
    if timing_constraints is not None and _is_feature_source(timing_constraints["source"]):
        payload["context"] = {"timing_constraints": timing_constraints}
    return payload


def _is_blocking_qor_record(record: dict) -> bool:
    metric_name = record.get("id")
    value = _qor_number(record.get("value"))
    if value is None:
        return False

    if metric_name in {
        "drc_count",
        "route_dr_total_violation_count",
        "route_la_total_overflow",
        "rcx_spef_parse_failure_count",
        "sta_setup_violation_count",
        "sta_hold_violation_count",
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


def _qor_evidence(
    source=None,
    operator: str | None = None,
    threshold=None,
    diagnosis: str | None = None,
    availability: str | None = None,
) -> dict:
    evidence = {}
    if _is_feature_source(source) or isinstance(source, dict):
        evidence["source"] = source
    if operator is not None:
        evidence["expected"] = {"operator": operator, "value": threshold}
    if diagnosis:
        evidence["diagnosis"] = diagnosis
    if availability:
        evidence["availability"] = availability
    return evidence


def _qor_expectation_diagnosis(metric_name: str, value, operator: str, threshold) -> str:
    return f"Observed {metric_name} = {value}; required condition is {operator} {threshold}."


def _qor_blocking_issue(record: dict) -> dict | None:
    if not _is_blocking_qor_record(record):
        return None

    metric_name = record.get("id")
    operator, threshold = ("not_applicable", None)
    value = record.get("value")
    return {
        "metric_id": metric_name,
        "display_name": record.get("display_name", metric_name),
        "value": value,
        "reason": "Removed V3 QoR blocker; use the V4 quality gates instead.",
        "evidence": _qor_evidence(
            source=record.get("source"),
            operator=operator,
            threshold=threshold,
            diagnosis=_qor_expectation_diagnosis(
                metric_name,
                value,
                operator,
                threshold,
            ),
        ),
    }


def _qor_missing_metrics(step: WorkspaceStep, records: list[dict]) -> list[str]:
    expected_metrics = QOR_EXPECTED_METRICS_BY_STEP.get(step.name, [])
    available_metrics = {
        record.get("id") for record in records if isinstance(record.get("id"), str)
    }
    return [metric_name for metric_name in expected_metrics if metric_name not in available_metrics]


def _qor_missing_metric_record(step: WorkspaceStep, metric_name: str) -> dict:
    source = _metric_feature_source(step, metric_name)
    if not _is_feature_source(source):
        diagnosis = f"No current feature source is configured for required metric {metric_name}."
        availability = "source_unconfigured"
    else:
        step_directory = step.directory
        feature_file = Path(step_directory) / source["path"] if step_directory is not None else None
        selector = source["selector"] or "the metric extraction input"
        if feature_file is None or not feature_file.is_file():
            diagnosis = (
                f"Required feature file {source['path']} is missing; cannot read "
                f"{selector} for {metric_name}."
            )
            availability = "source_file_missing"
        else:
            diagnosis = (
                f"Required field {selector} is absent or non-numeric in "
                f"{source['path']}; metric {metric_name} was not produced."
            )
            availability = "source_field_missing"
    return {
        "metric_id": metric_name,
        "reason": diagnosis,
        "evidence": _qor_evidence(
            source=source,
            diagnosis=diagnosis,
            availability=availability,
        ),
    }


def _workspace_step_completed(workspace: Workspace, step_name: str) -> bool:
    flow_data = workspace.flow.data
    flow_steps = flow_data.get("steps", []) if isinstance(flow_data, dict) else []
    if not isinstance(flow_steps, list) or len(flow_steps) == 0:
        return True

    for flow_step in flow_steps:
        if not isinstance(flow_step, dict) or flow_step.get("name") != step_name:
            continue
        return flow_step.get("state") == "Success"
    return False


def _harden_signoff_source(workspace: Workspace, source_step: str) -> dict:
    workspace_dir = workspace.directory
    summary_path = (
        Path(workspace_dir) / f"{source_step}_ecc" / "analysis" / "qor_summary.json"
        if workspace_dir is not None
        else None
    )
    summary = json_read(summary_path) if summary_path is not None else None
    available = (
        isinstance(summary, dict)
        and summary.get("schema_version") == 3
        and isinstance(summary.get("status"), str)
    )
    hard_gates = summary.get("hard_gates", []) if available else []
    return {
        "step": source_step,
        "flow_completed": _workspace_step_completed(workspace, source_step),
        "available": available,
        "status": summary.get("status") if available else None,
        "hard_gates": hard_gates if isinstance(hard_gates, list) else [],
    }


def _harden_source_passed(source: dict, required_hard_gates: tuple[str, ...]) -> bool:
    if not source["flow_completed"] or not source["available"]:
        return False
    if source["status"] != "pass":
        return False
    if len(required_hard_gates) == 0:
        return True

    gates = {
        gate.get("id"): gate
        for gate in source["hard_gates"]
        if isinstance(gate, dict) and isinstance(gate.get("id"), str)
    }
    return all(gates.get(gate_id, {}).get("passed") is True for gate_id in required_hard_gates)


def _harden_source_reason(source: dict, label: str) -> str:
    if not source["flow_completed"]:
        return f"{label} flow is not completed."
    if not source["available"]:
        return f"{label} QoR summary is missing."
    if source["status"] != "pass":
        return f"{label} QoR summary is {source['status']}."
    return f"{label} QoR hard gates are incomplete."


def _harden_qor_signoff(workspace: Workspace, records: list[dict]) -> dict:
    sources = []
    hard_gates = []
    blocking_issues = []
    records_by_id = {
        record.get("id"): record for record in records if isinstance(record.get("id"), str)
    }

    for spec in ():
        source = _harden_signoff_source(workspace, spec["step"])
        passed = _harden_source_passed(source, spec["required_hard_gates"])
        diagnosis = _harden_source_reason(source, spec["label"])
        analysis_source = {
            "kind": "analysis",
            "path": f"{spec['step']}_ecc/analysis/qor_summary.json",
            "selector": "/status",
        }
        sources.append(
            {
                "id": spec["id"],
                "step": source["step"],
                "analysis_file": "qor_summary.json",
                "available": source["available"],
                "flow_completed": source["flow_completed"],
                "status": source["status"],
            }
        )
        hard_gates.append(
            {
                "id": spec["id"],
                "passed": passed,
                "metric": f"{spec['step']}_qor_summary",
                "threshold": "pass",
                "actual": source["status"],
                "evidence": _qor_evidence(
                    source=analysis_source,
                    operator="==",
                    threshold="pass",
                    diagnosis=diagnosis,
                ),
            }
        )
        if not passed:
            blocking_issues.append(
                {
                    "metric_id": spec["id"],
                    "display_name": spec["label"],
                    "value": source["status"],
                    "reason": diagnosis,
                    "evidence": _qor_evidence(
                        source=analysis_source,
                        operator="==",
                        threshold="pass",
                        diagnosis=diagnosis,
                    ),
                }
            )

    values = {record.get("id"): _qor_number(record.get("value")) for record in records}
    artifact_missing_count = values.get("harden_artifact_missing_count")
    artifacts_complete = artifact_missing_count == 0
    source_gates_passed = all(gate["passed"] for gate in hard_gates)
    package_complete = artifacts_complete and source_gates_passed
    hard_gates.append(
        {
            "id": "final_package_complete",
            "passed": package_complete,
            "metric": "harden_artifact_missing_count",
            "threshold": 0,
            "actual": artifact_missing_count,
            "evidence": _qor_evidence(
                source=records_by_id.get("harden_artifact_missing_count", {}).get("source"),
                operator="==",
                threshold=0,
                diagnosis=_qor_expectation_diagnosis(
                    "harden_artifact_missing_count",
                    artifact_missing_count,
                    "==",
                    0,
                ),
            ),
        }
    )
    if not artifacts_complete:
        diagnosis = _qor_expectation_diagnosis(
            "harden_artifact_missing_count",
            artifact_missing_count,
            "==",
            0,
        )
        blocking_issues.append(
            {
                "metric_id": "final_package_complete",
                "display_name": "Final Package Complete",
                "value": artifact_missing_count,
                "reason": "Harden output artifacts are missing.",
                "evidence": _qor_evidence(
                    source=records_by_id.get("harden_artifact_missing_count", {}).get("source"),
                    operator="==",
                    threshold=0,
                    diagnosis=diagnosis,
                ),
            }
        )

    return {
        "sources": sources,
        "hard_gates": hard_gates,
        "blocking_issues": blocking_issues,
        "missing_sources": [
            source["id"]
            for source in sources
            if not source["available"] or not source["flow_completed"]
        ],
    }


def _sta_qor_hard_gates(records: list[dict]) -> list[dict]:
    values = {record.get("id"): _qor_number(record.get("value")) for record in records}
    records_by_id = {
        record.get("id"): record for record in records if isinstance(record.get("id"), str)
    }
    gate_specs = (
        ("sta_setup_wns_clean", "sta_setup_wns", ">=", 0.0, lambda value: value >= 0),
        ("sta_setup_tns_clean", "sta_setup_tns", ">=", 0.0, lambda value: value >= 0),
        (
            "sta_setup_violation_free",
            "sta_setup_violation_count",
            "==",
            0.0,
            lambda value: value == 0,
        ),
        ("sta_hold_wns_clean", "sta_hold_wns", ">=", 0.0, lambda value: value >= 0),
        ("sta_hold_tns_clean", "sta_hold_tns", ">=", 0.0, lambda value: value >= 0),
        (
            "sta_hold_violation_free",
            "sta_hold_violation_count",
            "==",
            0.0,
            lambda value: value == 0,
        ),
    )
    hard_gates = []
    for gate_id, metric, operator, threshold, predicate in gate_specs:
        actual = values.get(metric)
        hard_gates.append(
            {
                "id": gate_id,
                "passed": actual is not None and predicate(actual),
                "metric": metric,
                "threshold": threshold,
                "actual": actual,
                "evidence": _qor_evidence(
                    source=records_by_id.get(metric, {}).get("source"),
                    operator=operator,
                    threshold=threshold,
                    diagnosis=_qor_expectation_diagnosis(
                        metric,
                        actual,
                        operator,
                        threshold,
                    ),
                ),
            }
        )

    expected_count = values.get("sta_expected_corner_count")
    actual_count = values.get("sta_corner_count")
    hard_gates.append(
        {
            "id": "sta_corner_coverage_complete",
            "kind": "coverage",
            "passed": (
                expected_count is not None and expected_count > 0 and actual_count == expected_count
            ),
            "metric": "sta_corner_count",
            "threshold": expected_count,
            "actual": actual_count,
            "evidence": _qor_evidence(
                source=records_by_id.get("sta_corner_count", {}).get("source"),
                operator="==",
                threshold=expected_count,
                diagnosis=_qor_expectation_diagnosis(
                    "sta_corner_count",
                    actual_count,
                    "==",
                    expected_count,
                ),
            ),
        }
    )
    return hard_gates


def _signoff_readiness(step: WorkspaceStep) -> dict | None:
    if step.name not in {StepEnum.RCX.value, StepEnum.STA.value}:
        return None
    feature = json_read(step.feature.get("step", ""))
    feature_key = "rcx" if step.name == StepEnum.RCX.value else "sta"
    facts = feature.get(feature_key) if isinstance(feature, dict) else None
    signoff_metrics = facts.get("signoff_metrics") if isinstance(facts, dict) else None
    if not isinstance(signoff_metrics, dict):
        return {
            "status": "unavailable",
            "score_eligible": False,
            "reason_codes": [f"{feature_key}_signoff_metrics_unavailable"],
            "groups": [],
            "ocv": {"status": "unavailable"},
        }

    coverage = signoff_metrics.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    coverage_status = coverage.get("status", "unavailable")
    groups = [
        {
            "id": f"{feature_key}_corner_coverage"
            if feature_key == "rcx"
            else "sta_signoff_coverage",
            "status": coverage_status,
            "gate": True,
        }
    ]
    if feature_key == "rcx":
        parse_status = (
            "incomplete"
            if _qor_number(coverage.get("unparseable_count")) not in (None, 0)
            else coverage_status
        )
        groups.extend(
            (
                {"id": "rcx_parse_health", "status": parse_status, "gate": True},
                {
                    "id": "rcx_parasitic_envelope",
                    "status": (
                        signoff_metrics.get("parasitic_envelope", {}).get("status", "unavailable")
                        if isinstance(signoff_metrics.get("parasitic_envelope"), dict)
                        else "unavailable"
                    ),
                    "gate": False,
                },
            )
        )
    else:
        for group_id, key, gate in (
            ("sta_setup_closure", "setup", True),
            ("sta_hold_closure", "hold", True),
            ("sta_frequency_margin", "frequency", False),
        ):
            group = signoff_metrics.get(key)
            groups.append(
                {
                    "id": group_id,
                    "status": (
                        group.get("status", "unavailable")
                        if isinstance(group, dict)
                        else "unavailable"
                    ),
                    "gate": gate,
                }
            )

    gate_statuses = [group["status"] for group in groups if group["gate"]]
    if any(status == "blocked" for status in gate_statuses):
        status = "blocked"
    elif any(status == "incomplete" for status in gate_statuses):
        status = "incomplete"
    elif gate_statuses and all(status == "unavailable" for status in gate_statuses):
        status = "unavailable"
    elif gate_statuses and all(status == "pass" for status in gate_statuses):
        status = "pass"
    else:
        status = "incomplete"

    reason_codes = []
    if status == "unavailable":
        reason_codes.append(f"{feature_key}_signoff_not_configured")
    if _qor_number(coverage.get("missing_count")) not in (None, 0):
        reason_codes.append(f"{feature_key}_corner_summary_missing")
    if _qor_number(coverage.get("unparseable_count")) not in (None, 0):
        reason_codes.append(f"{feature_key}_corner_summary_unparseable")
    if feature_key == "sta":
        if any(
            group["id"] == "sta_setup_closure" and group["status"] == "blocked" for group in groups
        ):
            reason_codes.append("sta_setup_closure_failed")
        if any(
            group["id"] == "sta_hold_closure" and group["status"] == "blocked" for group in groups
        ):
            reason_codes.append("sta_hold_closure_failed")
    return {
        "status": status,
        "score_eligible": status == "pass",
        "reason_codes": reason_codes,
        "groups": groups,
        "ocv": {"status": "unavailable"},
    }


def _quality_gate(
    gate_id: str,
    title: str,
    state: str,
    metrics: list[dict],
    evidence: list[dict],
) -> dict:
    return {
        "id": gate_id,
        "title": title,
        "state": state,
        "blocking": True,
        "metrics": metrics,
        "evidence": evidence,
    }


def _quality_gate_metric(
    metric_id: str,
    actual,
    operator: str,
    expected,
    source: dict | None = None,
) -> dict:
    metric = {
        "id": metric_id,
        "actual": actual,
        "operator": operator,
        "expected": expected,
    }
    if _is_feature_source(source):
        metric["source"] = source
    return metric


def _quality_gate_evidence(*sources: dict | None) -> list[dict]:
    evidence = []
    seen = set()
    for source in sources:
        if not _is_feature_source(source):
            continue
        key = (source.get("kind"), source.get("path"), source.get("selector"))
        if key in seen:
            continue
        seen.add(key)
        evidence.append(source)
    return evidence


def _gate_state(*, available: bool, passed: bool) -> str:
    if not available:
        return "unavailable"
    return "pass" if passed else "failed"


def _quality_gates(step: WorkspaceStep, records: list[dict]) -> list[dict]:
    records_by_id = {
        record.get("id"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }

    def metric(metric_id: str):
        record = records_by_id.get(metric_id, {})
        return _qor_number(record.get("value")), record.get("source")

    if step.name == StepEnum.DRC.value:
        count, source = metric("drc_count")
        return [
            _quality_gate(
                "qor.drc.clean",
                "Final DRC clean",
                _gate_state(available=count is not None, passed=count == 0),
                [_quality_gate_metric("drc_count", count, "==", 0, source)],
                _quality_gate_evidence(source),
            )
        ]

    feature = json_read(step.feature.get("step", ""))
    feature = feature if isinstance(feature, dict) else {}

    if step.name == StepEnum.RCX.value:
        signoff = feature.get("rcx", {}).get("signoff_metrics", {})
        coverage = signoff.get("coverage", {}) if isinstance(signoff, dict) else {}
        expected, expected_source = metric("rcx_expected_corner_count")
        available, available_source = metric("rcx_spef_file_count")
        missing, missing_source = metric("rcx_missing_corner_count")
        parse_failures, parse_source = metric("rcx_spef_parse_failure_count")
        coverage_available = (
            isinstance(coverage, dict)
            and expected is not None
            and available is not None
            and missing is not None
            and expected > 0
        )
        coverage_passed = (
            coverage_available
            and coverage.get("status") == "pass"
            and available == expected
            and missing == 0
        )
        parse_available = coverage_available and parse_failures is not None
        parse_passed = parse_available and parse_failures == 0
        return [
            _quality_gate(
                "qor.rcx.corner_coverage",
                "RCX corner coverage",
                _gate_state(available=coverage_available, passed=coverage_passed),
                [
                    _quality_gate_metric(
                        "rcx_expected_corner_count", expected, ">", 0, expected_source
                    ),
                    _quality_gate_metric(
                        "rcx_spef_file_count", available, "==", expected, available_source
                    ),
                    _quality_gate_metric(
                        "rcx_missing_corner_count", missing, "==", 0, missing_source
                    ),
                ],
                _quality_gate_evidence(expected_source, available_source, missing_source),
            ),
            _quality_gate(
                "qor.rcx.spef_parse_health",
                "RCX SPEF integrity",
                _gate_state(available=parse_available, passed=parse_passed),
                [
                    _quality_gate_metric(
                        "rcx_spef_parse_failure_count", parse_failures, "==", 0, parse_source
                    )
                ],
                _quality_gate_evidence(parse_source),
            ),
        ]

    if step.name == StepEnum.STA.value:
        signoff = feature.get("sta", {}).get("signoff_metrics", {})
        coverage = signoff.get("coverage", {}) if isinstance(signoff, dict) else {}
        setup = signoff.get("setup", {}) if isinstance(signoff, dict) else {}
        hold = signoff.get("hold", {}) if isinstance(signoff, dict) else {}
        coverage_status = coverage.get("status") if isinstance(coverage, dict) else None
        coverage_available = coverage_status == "pass"
        setup_wns, setup_wns_source = metric("sta_setup_wns")
        setup_tns, setup_tns_source = metric("sta_setup_tns")
        setup_nvp, setup_nvp_source = metric("sta_setup_violation_count")
        hold_wns, hold_wns_source = metric("sta_hold_wns")
        hold_tns, hold_tns_source = metric("sta_hold_tns")
        hold_nvp, hold_nvp_source = metric("sta_hold_violation_count")
        setup_available = (
            coverage_available
            and all(value is not None for value in (setup_wns, setup_tns, setup_nvp))
            and isinstance(setup, dict)
        )
        hold_available = (
            coverage_available
            and all(value is not None for value in (hold_wns, hold_tns, hold_nvp))
            and isinstance(hold, dict)
        )
        setup_passed = (
            setup_available
            and setup.get("status") == "pass"
            and setup_wns >= 0
            and setup_tns >= 0
            and setup_nvp == 0
        )
        hold_passed = (
            hold_available
            and hold.get("status") == "pass"
            and hold_wns >= 0
            and hold_tns >= 0
            and hold_nvp == 0
        )
        return [
            _quality_gate(
                "qor.sta.setup_closed",
                "STA setup closure",
                _gate_state(available=setup_available, passed=setup_passed),
                [
                    _quality_gate_metric("sta_setup_wns", setup_wns, ">=", 0, setup_wns_source),
                    _quality_gate_metric("sta_setup_tns", setup_tns, ">=", 0, setup_tns_source),
                    _quality_gate_metric(
                        "sta_setup_violation_count", setup_nvp, "==", 0, setup_nvp_source
                    ),
                ],
                _quality_gate_evidence(setup_wns_source, setup_tns_source, setup_nvp_source),
            ),
            _quality_gate(
                "qor.sta.hold_closed",
                "STA hold closure",
                _gate_state(available=hold_available, passed=hold_passed),
                [
                    _quality_gate_metric("sta_hold_wns", hold_wns, ">=", 0, hold_wns_source),
                    _quality_gate_metric("sta_hold_tns", hold_tns, ">=", 0, hold_tns_source),
                    _quality_gate_metric(
                        "sta_hold_violation_count", hold_nvp, "==", 0, hold_nvp_source
                    ),
                ],
                _quality_gate_evidence(hold_wns_source, hold_tns_source, hold_nvp_source),
            ),
        ]

    return []


def build_qor_summary_payload(
    workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics
) -> dict:
    qor_metrics = build_qor_metrics_payload(
        workspace=workspace,
        step=step,
        step_metrics=step_metrics,
    )
    records = qor_metrics["metrics"]
    dimensions = {}
    for record in records:
        dimension = record.get("category", "unknown")
        dimensions.setdefault(dimension, {"metric_count": 0})
        dimensions[dimension]["metric_count"] += 1

    missing_metrics = _qor_missing_metrics(step, records)
    integrity = qor_metrics.get("integrity")
    invalid_metric_source_ids = set(
        integrity.get("invalid_metric_source_ids", []) if isinstance(integrity, dict) else []
    )
    analysis_status = (
        "valid"
        if records and not missing_metrics and not invalid_metric_source_ids
        else "incomplete"
    )
    gates = _quality_gates(step, records)
    if any(gate["state"] == "failed" for gate in gates):
        quality_status = "blocked"
    elif any(gate["state"] == "unavailable" for gate in gates):
        quality_status = "incomplete"
    else:
        quality_status = "pass"

    return {
        "schema_version": 4,
        "analysis_revision": QOR_ANALYSIS_REVISION,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "analysis_status": analysis_status,
        "quality_status": quality_status,
        "metric_count": len(records),
        "dimensions": dimensions,
        "gates": gates,
        "missing_metrics": [
            _qor_missing_metric_record(step, metric_id)
            if metric_id not in invalid_metric_source_ids
            else {
                "metric_id": metric_id,
                "reason": (
                    f"Metric {metric_id} resolved outside the current step feature "
                    "directory and was rejected."
                ),
                "evidence": _qor_evidence(
                    diagnosis=(
                        f"Metric {metric_id} resolved outside the current step feature "
                        "directory and was rejected."
                    ),
                    availability="invalid_source",
                ),
            }
            for metric_id in missing_metrics
        ],
        "metrics_file": "qor_metrics.json",
    }


def _qor_hotspot_record(record: dict) -> dict | None:
    metric_name = record.get("id")
    hint = QOR_HOTSPOT_METRIC_HINTS.get(metric_name)
    if hint is None:
        return None

    value = _qor_number(record.get("value"))
    if value is None or value <= 0:
        return None

    return {
        "kind": hint["kind"],
        "severity": hint["severity"],
        "metric_id": metric_name,
        "display_name": record.get("display_name", metric_name),
        "value": record.get("value"),
        "unit": record.get("unit"),
        "category": record.get("category"),
        "source": record.get("source"),
        "description": hint["description"],
    }


def _drc_rule_display_name(rule: str) -> str:
    characters = []
    for index, character in enumerate(rule):
        previous = rule[index - 1] if index else ""
        if character.isupper() and (previous.islower() or previous.isdigit()):
            characters.append(" ")
        characters.append(character)

    return " ".join("".join(characters).replace("_", " ").replace("-", " ").split())


def _drc_rule_layer_hotspot_records(step: WorkspaceStep) -> list[dict]:
    feature_path = step.feature.get("step")
    if feature_path is None:
        return []

    feature = json_read(feature_path)
    if not isinstance(feature, dict):
        return []
    drc = feature.get("drc")
    if not isinstance(drc, dict):
        return []
    distribution = drc.get("distribution")
    if not isinstance(distribution, dict):
        return []

    records = []
    for raw_rule, rule_data in distribution.items():
        if not isinstance(raw_rule, str) or not raw_rule.strip():
            continue
        if not isinstance(rule_data, dict):
            continue
        layers = rule_data.get("layers")
        if not isinstance(layers, dict):
            continue

        for raw_layer, layer_data in layers.items():
            if not isinstance(raw_layer, str) or not raw_layer.strip():
                continue
            if not isinstance(layer_data, dict):
                continue
            value = _qor_number(layer_data.get("number"))
            if value is None or value <= 0:
                continue
            records.append((raw_rule, raw_layer, value))

    records.sort(key=lambda item: (-float(item[2]), item[0], item[1]))
    source_file = _relative_step_path(step, feature_path)
    hotspots = []
    for raw_rule, raw_layer, value in records[:10]:
        display_rule = _drc_rule_display_name(raw_rule)
        hotspots.append(
            {
                "kind": "drc_rule_layer",
                "severity": "critical",
                "metric_id": f"drc:{raw_rule}:{raw_layer}",
                "display_name": f"{display_rule} · {raw_layer}",
                "value": value,
                "unit": "count",
                "category": "clock_robustness_dfm",
                "source": {
                    "kind": "feature",
                    "path": source_file,
                    "selector": f"/drc/distribution/{raw_rule}/layers/{raw_layer}",
                },
                "description": f"{value} DRC violations: {display_rule} on {raw_layer}.",
            }
        )
    return hotspots


def build_qor_hotspots_payload(
    workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics
) -> dict:
    qor_metrics = build_qor_metrics_payload(
        workspace=workspace,
        step=step,
        step_metrics=step_metrics,
    )
    hotspots = []

    for record in qor_metrics["metrics"]:
        hotspot = _qor_hotspot_record(record)
        if hotspot is not None:
            hotspots.append(hotspot)

    if step.name == StepEnum.DRC.value:
        hotspots.extend(_drc_rule_layer_hotspot_records(step))

    return {
        "schema_version": 3,
        "analysis_revision": QOR_ANALYSIS_REVISION,
        "tool": step.tool,
        "step": step.name,
        "design": workspace.design.name,
        "hotspots": hotspots,
    }


def save_qor_metrics(workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics) -> bool:
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


def save_qor_summary(workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics) -> bool:
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


def save_qor_hotspots(workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics) -> bool:
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


def _remove_legacy_step_metric_artifacts(step: WorkspaceStep) -> bool:
    analysis_dir = step.analysis.get("dir")
    if analysis_dir is None or analysis_dir == "":
        return True

    legacy_prefix = f"{step.name}_metrics"
    try:
        for suffix in (".json", ".png"):
            legacy_path = Path(analysis_dir) / f"{legacy_prefix}{suffix}"
            if legacy_path.is_file():
                legacy_path.unlink()
    except OSError:
        return False
    return True


def save_step_metrics(workspace: Workspace, step: WorkspaceStep, step_metrics: StepMetrics) -> bool:
    if not save_qor_metrics(workspace=workspace, step=step, step_metrics=step_metrics):
        return False
    if not save_qor_summary(workspace=workspace, step=step, step_metrics=step_metrics):
        return False
    if not save_qor_hotspots(workspace=workspace, step=step, step_metrics=step_metrics):
        return False
    return _remove_legacy_step_metric_artifacts(step)


def build_step_metrics(
    workspace: Workspace, step: WorkspaceStep, subflow: EccSubFlow = None
) -> StepMetrics:
    """
    Build and return a StepMetrics instance for the given workspace step.
    """
    # update sub flow metrics state
    sub_flow = (
        subflow if subflow is not None else EccSubFlow(workspace=workspace, workspace_step=step)
    )

    # step matrics
    metrics = None
    match step.name:
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

    sub_flow.update_step(
        step_name=EccSubFlowEnum.analysis.value,
        state=StateEnum.Invalid if metrics is None else StateEnum.Success,
        info=info,
    )

    workspace.logger.info("\nmetrics - \n%s", dict_to_str(metrics.data))
    return metrics


def build_metrics_timing(workspace: Workspace, step: WorkspaceStep) -> dict:
    metrics = {}

    data = json_read(step.feature.get("timing", ""))
    max_WNS = None
    if isinstance(data, dict) and len(data) > 0:
        for slack_item in data.get("slack", []):
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


def build_metrics_db(workspace: Workspace, step: WorkspaceStep) -> dict:
    # db summary matrics
    metrics = {}

    metrics["Tool"] = step.tool

    data = json_read(step.feature.get("db", ""))
    if isinstance(data, dict):
        layout = data.get("Design Layout", {})
        statistics = data.get("Design Statis", {})
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


def build_metrics_floorplan(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return floorplan metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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


def build_metrics_net_opt(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return net operation metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    json_path = step.feature.get("step", "")
    db_data = json_read(step.feature.get("db", ""))
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


def build_metrics_filler(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return filler metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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


def build_metrics_drc(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return DRC metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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


def build_metrics_routing(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return routing metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("db", "")
    data = json_read(json_path)
    if isinstance(data, dict):
        nets = data.get("Nets", {})
        if isinstance(nets, dict):
            _add_number_metric(metrics, "wire_len", nets.get("wire_len"))
            _add_number_metric(metrics, "num_via", nets.get("num_via"))

    route_data = json_read(step.feature.get("step", ""))
    if isinstance(route_data, dict):
        route = route_data.get("route", {})
        route = route if isinstance(route, dict) else {}
        metrics["route_layer_metrics"] = _route_layer_metrics(
            route,
            step.feature.get("step", ""),
        )
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


def build_metrics_rcx(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build RCX metrics from its bounded feature facts.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))
    feature = json_read(step.feature.get("step", ""))
    rcx = feature.get("rcx") if isinstance(feature, dict) else None
    rcx = rcx if isinstance(rcx, dict) else {}
    signoff_metrics = rcx.get("signoff_metrics")
    signoff_metrics = signoff_metrics if isinstance(signoff_metrics, dict) else {}
    for metric_id, feature_key in (
        ("rcx_spef_file_count", "spef_file_count"),
        ("rcx_expected_corner_count", "expected_corner_count"),
        ("rcx_missing_corner_count", "missing_corner_count"),
        ("rcx_output_def_exists", "output_def_exists"),
        ("rcx_output_gds_exists", "output_gds_exists"),
    ):
        _add_number_metric(metrics, metric_id, rcx.get(feature_key))

    electrical_summary = rcx.get("electrical_summary")
    electrical_summary = electrical_summary if isinstance(electrical_summary, dict) else {}
    for metric_id, feature_key in (
        ("rcx_spef_parse_failure_count", "parse_failure_count"),
        ("rcx_worst_total_capacitance_ff", "worst_total_capacitance_ff"),
        ("rcx_worst_coupling_capacitance_ff", "worst_coupling_capacitance_ff"),
        ("rcx_worst_total_resistance_ohm", "worst_total_resistance_ohm"),
    ):
        _add_number_metric(metrics, metric_id, electrical_summary.get(feature_key))
    if electrical_summary:
        metrics["rcx_electrical_corner_metrics"] = {
            "schema_version": electrical_summary.get("schema_version"),
            "parsed_corner_count": electrical_summary.get("parsed_corner_count"),
            "parse_failure_count": electrical_summary.get("parse_failure_count"),
            "worst_total_capacitance_ff": electrical_summary.get("worst_total_capacitance_ff"),
            "worst_coupling_capacitance_ff": electrical_summary.get(
                "worst_coupling_capacitance_ff"
            ),
            "worst_total_resistance_ohm": electrical_summary.get("worst_total_resistance_ohm"),
            "coverage": signoff_metrics.get("coverage"),
            "rc_corners": signoff_metrics.get("rc_corners", []),
        }

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_sta(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build STA multi-corner timing summary metrics.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))

    feature_dir = Path(step.feature.get("dir", ""))
    qor_paths = sta_qor_summary_paths(workspace, feature_dir)
    summaries = [
        summary
        for corner, feature_path in qor_paths
        if (summary := read_sta_qor_summary(corner, feature_path)) is not None
    ]
    timing_paths = sta_timing_paths_paths(workspace, feature_dir)
    timing_artifacts = [
        artifact
        for corner, feature_path in timing_paths
        if (artifact := read_sta_timing_paths(corner, feature_path)) is not None
    ]
    if not _save_sta_timing_issues(
        workspace=workspace,
        step=step,
        timing_artifacts=timing_artifacts,
        expected_paths=timing_paths,
    ):
        return None
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

    loaded_corners = {summary.corner for summary in summaries}
    expected_corners = [corner for corner, _ in qor_paths]
    signoff_metrics = _sta_signoff_metrics(
        workspace=workspace,
        step=step,
        qor_paths=qor_paths,
        summaries=summaries,
        setup_wns=setup_wns,
        setup_corner=setup_corner,
        setup_tns=setup_tns,
        setup_tns_corner=setup_tns_corner,
        setup_violation_count=setup_violation_count,
        hold_wns=hold_wns,
        hold_corner=hold_corner,
        hold_tns=hold_tns,
        hold_tns_corner=hold_tns_corner,
        hold_violation_count=hold_violation_count,
        frequency=frequency,
        frequency_corner=frequency_corner,
    )
    corner_contexts = {
        corner["sta_corner"]: {
            key: value
            for key, value in corner.items()
            if key not in {"availability", "reason", "summary_file"}
        }
        for corner in signoff_metrics["corners"]
    }
    metrics["sta_path_group_metrics"] = _sta_path_group_metrics(summaries, corner_contexts)
    if not _save_step_feature_facts(
        step,
        "sta",
        {
            "corner_count": metrics["sta_corner_count"],
            "expected_corner_count": metrics["sta_expected_corner_count"],
            "missing_corner_count": metrics["sta_missing_corner_count"],
            "setup_violation_count": setup_violation_count,
            "hold_violation_count": hold_violation_count,
            "loaded_corners": sorted(loaded_corners),
            "missing_corners": [
                corner for corner in expected_corners if corner not in loaded_corners
            ],
            "signoff_metrics": signoff_metrics,
        },
    ):
        return None

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_harden(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build final harden package completeness metrics.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}
    metrics.update(build_metrics_db(workspace, step))

    output_dir = step.output.get("dir", "")
    # Final delivery requires the implementation artifacts.  The LIB source
    # audit TSV is no longer emitted by STA, and preview rendering is a UI aid
    # generated after analysis, so neither belongs to package completeness.
    artifact_checks = {
        "harden_gds_exists": _artifact_exists(step.output.get("gds", ""), output_dir, "*.gds"),
        "harden_lef_exists": _artifact_exists(step.output.get("lef", ""), output_dir, "*.lef"),
        "harden_lib_exists": _artifact_exists(step.output.get("lib", ""), output_dir, "*.lib"),
    }
    metrics.update(artifact_checks)
    metrics["harden_artifact_missing_count"] = sum(
        1 for exists in artifact_checks.values() if exists == 0
    )
    if not _save_step_feature_facts(
        step,
        "harden",
        {
            "artifacts": artifact_checks,
            "artifact_missing_count": metrics["harden_artifact_missing_count"],
        },
    ):
        return None

    step_metrics.data = metrics
    image_path = str(step.output.get("image", ""))
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_legalization(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return legalization metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # Current legalization feature output only carries run facts.  Movement
    # totals are no longer emitted by the tool, so do not synthesize a stale
    # V3 metric requirement from an absent legacy field.
    json_path = step.feature.get("step", "")

    step_metrics.data = metrics

    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_timing_opt_hold(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (hold) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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


def build_metrics_timing_opt_drv(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (driver) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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


def build_metrics_cts(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return CTS metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # step matrics
    json_path = step.feature.get("step", "")
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
        timing_quality = cts.get("timing_quality")
        timing_quality = timing_quality if isinstance(timing_quality, dict) else {}
        if timing_quality.get("availability") == "available":
            _add_number_metric(
                metrics,
                "cts_worst_optimized_skew_ns",
                timing_quality.get("worst_optimized_skew_ns"),
            )
            _add_number_metric(
                metrics,
                "cts_worst_max_insertion_latency_ns",
                timing_quality.get("worst_max_insertion_latency_ns"),
            )
            _add_number_metric(
                metrics,
                "cts_skew_target_unmet_count",
                timing_quality.get("target_unmet_count"),
            )
            metrics["cts_clock_skew_metrics"] = {
                "schema_version": timing_quality.get("schema_version"),
                "clock_count": timing_quality.get("clock_count"),
                "target_unmet_count": timing_quality.get("target_unmet_count"),
                "worst_optimized_skew_ns": timing_quality.get("worst_optimized_skew_ns"),
                "worst_max_insertion_latency_ns": timing_quality.get(
                    "worst_max_insertion_latency_ns"
                ),
            }

    step_metrics.data = metrics

    # generate report image and dscription
    image_path = str(json_path).replace(".json", ".png")
    report = f"{step.name} step metrics:\n"

    step_metrics.report.append((image_path, report))

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    else:
        return None


def build_metrics_placement(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    Build and return placement metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis["metrics"]

    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))

    # Placement congestion and wirelength are emitted through place.map.json.
    # The old place.step.json overflow/bin fields are not part of the current
    # DreamPlace feature contract.
    json_path = step.feature.get("step", "")

    map_data = json_read(step.feature.get("map", ""))
    if isinstance(map_data, dict):
        metrics["place_map_metrics"] = _place_map_metrics(
            map_data,
            step.feature.get("map", ""),
        )
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
