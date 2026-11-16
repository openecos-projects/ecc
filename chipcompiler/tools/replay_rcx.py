"""Read ECC SPEF node coordinates and electrical edges without rerunning extraction."""

import math
import re
from decimal import Decimal
from pathlib import Path

from chipcompiler.tools.ecc.metrics import (
    _SPEF_CAPACITANCE_UNIT_TO_FF,
    _SPEF_RESISTANCE_UNIT_TO_OHM,
    _spef_entry_value,
    _spef_unit_scale,
)
from chipcompiler.utility.gzip import read_text_maybe_gzip


def network_views(path: Path, def_path: Path):
    units = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", read_text_maybe_gzip(def_path))
    if units is None or int(units[1]) <= 0:
        raise ValueError("SPEF coordinates require the producing DEF's DBU units")
    dbu = int(units[1])
    names, nodes, nets = {}, {}, []
    cap_scale = res_scale = None
    section, current, delimiter = "", None, ":"
    with path.open() as stream:
        for line in stream:
            tokens = line.split("//", 1)[0].split()
            if not tokens:
                continue
            tag = tokens[0]
            if tag == "*C_UNIT":
                cap_scale = _spef_unit_scale(tokens, _SPEF_CAPACITANCE_UNIT_TO_FF)
            elif tag == "*R_UNIT":
                res_scale = _spef_unit_scale(tokens, _SPEF_RESISTANCE_UNIT_TO_OHM)
            elif tag == "*DELIMITER":
                delimiter = tokens[1]
            elif tag == "*NAME_MAP":
                section = "names"
            elif tag == "*D_NET":
                current = {"id": tokens[1], "nodes": [], "resistors": [], "capacitors": []}
                nets.append(current)
                section = ""
            elif tag in {"*CONN", "*CAP", "*RES"}:
                section = tag[1:].lower()
            elif tag == "*END":
                section, current = "", None
            elif section == "names" and tag.startswith("*") and tag[1:].isdigit():
                names[tag] = " ".join(tokens[1:])
            elif section == "conn" and current is not None and tag in {"*P", "*I", "*N"}:
                node = {"id": tokens[1], "type": tag[1:]}
                if "*C" in tokens:
                    offset = tokens.index("*C") + 1
                    # ECC SPEFWriter converts native DBU to microns (3 decimals).
                    node["position"] = [
                        int((Decimal(v) * dbu).to_integral_value())
                        for v in tokens[offset : offset + 2]
                    ]
                    if len(node["position"]) != 2:
                        raise ValueError("Truncated SPEF node coordinates")
                    nodes[node["id"]] = node["position"]
                current["nodes"].append(node)
            elif current is not None and section in {"cap", "res"} and tag.isdigit():
                scale = cap_scale if section == "cap" else res_scale
                value = _spef_entry_value(tokens)
                if value is None or scale is None or value < 0 or not math.isfinite(value):
                    raise ValueError("Invalid SPEF element value or missing units")
                expected = {3, 4} if section == "cap" else {4}
                if len(tokens) not in expected:
                    raise ValueError("Malformed SPEF element")
                current["capacitors" if section == "cap" else "resistors"].append(
                    {"nodes": tokens[1:-1], "value": value * scale}
                )
            elif tag.startswith("*"):
                section = ""

    def label(node):
        owner, separator, pin = node.partition(delimiter)
        return names.get(owner, owner) + (separator + pin if separator else "")

    items = []
    for net in nets:
        positions = [node["position"] for node in net["nodes"] if "position" in node]
        segments, missing = [], 0
        for element in net["resistors"]:
            a, b = element["nodes"]
            if a in nodes and b in nodes:
                segments.append([nodes[a], nodes[b]])
            else:
                missing += 1
        ground = sum(c["value"] for c in net["capacitors"] if len(c["nodes"]) == 1)
        items.append(
            {
                "label": label(net["id"]),
                "positions": positions,
                "segments": segments,
                "details": {
                    "nodes": [{**node, "name": label(node["id"])} for node in net["nodes"]],
                    "resistors_ohm": net["resistors"],
                    "capacitors_ff": net["capacitors"],
                    "ground_capacitance_ff": ground,
                    "unlocated_resistors": missing,
                },
            }
        )
    return [
        {
            "label": f"{path.stem} · RC network",
            "kind": "rc_network",
            "items": items,
            "summary": {
                "reported_nets": len(items),
                "dbu_per_micron": dbu,
                "coordinate_precision_um": 0.001,
                "display": "Resistor branches and nodes; electrical graph, not routing geometry",
                "capacitance": "Incident entries per net; coupling may occur in both nets",
                "unlocated_resistors": sum(
                    item["details"]["unlocated_resistors"] for item in items
                ),
            },
        }
    ]
