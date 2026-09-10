"""Bounded dashboard detail facts derived from step feature JSON."""

from math import isfinite
from typing import Any

from chipcompiler.utility import json_read

_INSTANCE_CLASS_LIMIT = 32
_LAYER_RECORD_LIMIT = 64
_PIN_DISTRIBUTION_LIMIT = 64
_LVS_RECORD_LIMIT = 100


def qor_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value if isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
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
        if not isfinite(number):
            return None
        return int(number) if number.is_integer() else number
    return None


def database_fact_summary(feature_path) -> dict | None:
    data = json_read(feature_path or "")
    if not isinstance(data, dict):
        return None
    layout = data.get("Design Layout")
    statistics = data.get("Design Statis")
    instances = data.get("Instances")
    pins = data.get("Pins")
    layers = data.get("Layers")
    nets = data.get("Nets")
    layout = layout if isinstance(layout, dict) else {}
    statistics = statistics if isinstance(statistics, dict) else {}
    instances = instances if isinstance(instances, dict) else {}
    pins = pins if isinstance(pins, dict) else {}
    layers = layers if isinstance(layers, dict) else {}
    nets = nets if isinstance(nets, dict) else {}

    def instance_record(kind, value):
        value = value if isinstance(value, dict) else {}
        return {
            "kind": kind,
            "count": qor_number(value.get("num")),
            "area": qor_number(value.get("area")),
            "pin_count": qor_number(value.get("pin_num")),
        }

    def layer_records(value, source_metric, output_metric):
        if not isinstance(value, list):
            return []
        records = []
        for index, item in enumerate(value[:_LAYER_RECORD_LIMIT]):
            if not isinstance(item, dict):
                continue
            layer = item.get("layer_name")
            records.append(
                {
                    "layer": layer if isinstance(layer, str) and layer else f"Layer {index + 1}",
                    output_metric: qor_number(item.get(source_metric)),
                }
            )
        return records

    pin_distribution = pins.get("pin_distribution")
    summary = {
        "schema_version": 1,
        "layout": {
            "die_area": qor_number(layout.get("die_area")),
            "die_usage": qor_number(layout.get("die_usage")),
            "die_width": qor_number(layout.get("die_bounding_width")),
            "die_height": qor_number(layout.get("die_bounding_height")),
            "core_area": qor_number(layout.get("core_area")),
            "core_usage": qor_number(layout.get("core_usage")),
            "core_width": qor_number(layout.get("core_bounding_width")),
            "core_height": qor_number(layout.get("core_bounding_height")),
            "dbu": qor_number(layout.get("design_dbu")),
        },
        "statistics": {
            "io_pins": qor_number(statistics.get("num_iopins")),
            "instances": qor_number(statistics.get("num_instances")),
            "nets": qor_number(statistics.get("num_nets")),
            "pdn": qor_number(statistics.get("num_pdn")),
        },
        "instance_classes": [
            instance_record(kind, value)
            for kind, value in sorted(instances.items())
            if kind != "total" and isinstance(kind, str) and isinstance(value, dict)
        ][:_INSTANCE_CLASS_LIMIT],
        "instance_total": instance_record("total", instances.get("total")),
        "pin_distribution": [
            {
                "pin_count": int(pin_count),
                "instance_count": qor_number(item.get("inst_num")),
                "net_count": qor_number(item.get("net_num")),
            }
            for item in (
                pin_distribution[:_PIN_DISTRIBUTION_LIMIT]
                if isinstance(pin_distribution, list)
                else []
            )
            if isinstance(item, dict)
            and (pin_count := qor_number(item.get("pin_num"))) is not None
            and pin_count >= 0
            and float(pin_count).is_integer()
        ],
        "cut_layers": layer_records(layers.get("cut_layers"), "via_num", "via_count"),
        "routing_layers": layer_records(layers.get("routing_layers"), "wire_len", "wire_length"),
        "wire_length": qor_number(nets.get("wire_len")),
        "via_count": qor_number(nets.get("num_via")),
    }
    scalar_groups = (summary["layout"], summary["statistics"])
    has_instance_total = any(
        summary["instance_total"][key] is not None for key in ("count", "area", "pin_count")
    )
    if (
        not has_instance_total
        and not any(value is not None for group in scalar_groups for value in group.values())
        and not any(
            summary[key]
            for key in ("instance_classes", "pin_distribution", "cut_layers", "routing_layers")
        )
        and summary["wire_length"] is None
        and summary["via_count"] is None
    ):
        return None
    return summary


def lvs_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return value.strip() if isinstance(value, str) else ""


def lvs_detail_summary(feature_path) -> dict | None:
    feature = json_read(feature_path or "")
    if not isinstance(feature, dict):
        return None
    section = feature.get("lvs", feature)
    if not isinstance(section, dict):
        return None
    entities = []
    raw_entities = section.get("entity", [])
    for item in raw_entities[:_LVS_RECORD_LIMIT] if isinstance(raw_entities, list) else []:
        if not isinstance(item, dict) or not lvs_text(item.get("entity")):
            continue
        entities.append(
            {
                "entity": lvs_text(item.get("entity")),
                "netlist": qor_number(item.get("netlist")),
                "def": qor_number(item.get("def")),
                "difference": qor_number(item.get("difference")),
            }
        )
    connectivity = []
    raw_connectivity = section.get("connectivity", [])
    for item in raw_connectivity[:_LVS_RECORD_LIMIT] if isinstance(raw_connectivity, list) else []:
        if not isinstance(item, dict) or not lvs_text(item.get("connectivity")):
            continue
        connectivity.append(
            {
                "connectivity": lvs_text(item.get("connectivity")),
                "open": qor_number(item.get("open")),
                "short": qor_number(item.get("short")),
                "connected": qor_number(item.get("connected")),
                "total": qor_number(item.get("total")),
            }
        )
    violations = []
    raw_violations = section.get("violations", [])
    for item in raw_violations[:_LVS_RECORD_LIMIT] if isinstance(raw_violations, list) else []:
        if not isinstance(item, dict):
            continue
        violation_type = lvs_text(item.get("type"))
        if not violation_type:
            continue
        violations.append(
            {
                "type": violation_type,
                "net": lvs_text(item.get("net")),
                "instance": lvs_text(item.get("instance")),
                "terminals": lvs_text(item.get("terminals")),
                "components": lvs_text(item.get("components")),
            }
        )
    return {
        "schema_version": 1,
        "entities": entities,
        "connectivity": connectivity,
        "violations": violations,
    }
