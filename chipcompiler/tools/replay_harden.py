"""Inspect generated abstracts, preserving exported units and source geometry."""

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from chipcompiler.utility.gzip import read_text_maybe_gzip


def lef_views(path: Path, def_path: Path):
    """Read the rectangular LEF subset emitted by ECC's abstract writer."""
    header = read_text_maybe_gzip(def_path)
    units = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", header)
    die = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", header)
    if units is None or die is None:
        raise ValueError("Abstract LEF has no validated DEF unit/origin basis")
    dbu = int(units[1])
    origin = [int(die[1]), int(die[2])]
    pin, layer, context = None, "", ""
    groups = defaultdict(list)
    unsupported = []
    for line in path.read_text().splitlines():
        tokens = line.strip().rstrip(";").split()
        if not tokens:
            continue
        if tokens[0] == "PIN" and len(tokens) == 2:
            pin, context = tokens[1], "pin"
        elif tokens[0] == "OBS":
            pin, context = None, "obstruction"
        elif tokens[0] == "LAYER" and len(tokens) >= 2:
            layer = tokens[1]
        elif tokens[0] == "END" and (
            len(tokens) == 1 and context == "obstruction" or pin and tokens[-1] == pin
        ):
            pin, context = None, ""
        elif tokens[0] == "ORIGIN" and tokens[1:3] != ["0.0", "0.0"]:
            if any(Decimal(value) != 0 for value in tokens[1:3]):
                raise ValueError("Nonzero abstract origin requires an explicit placement transform")
        elif tokens[0] == "SIZE" and len(tokens) == 4 and tokens[2] == "BY":
            w, h = (
                int((Decimal(value) * dbu).to_integral_value()) for value in (tokens[1], tokens[3])
            )
            groups["boundary"].append(
                {"label": path.stem, "bboxes": [[*origin, origin[0] + w, origin[1] + h]]}
            )
        elif tokens[0] == "RECT" and context and len(tokens) == 5:
            # ECC's abstract writer exports iDB coordinates directly, including
            # a nonzero die origin. Adding the origin again would shift pins/OBS.
            coords = [int((Decimal(value) * dbu).to_integral_value()) for value in tokens[1:]]
            if coords[0] > coords[2] or coords[1] > coords[3]:
                raise ValueError("Inverted abstract rectangle")
            groups[f"{context} · {layer}"].append(
                {
                    "label": pin or f"OBS {layer}",
                    "bboxes": [coords],
                    "details": {"layer": layer, "pin": pin, "export_unit": "um"},
                }
            )
        elif tokens[0] in {"POLYGON", "PATH", "VIA"} and context:
            unsupported.append(line.strip())
    return [
        {
            "label": f"LEF · {name}",
            "kind": "abstract",
            "items": items,
            "summary": {
                "dbu_per_micron": dbu,
                "origin_dbu": origin,
                "coordinate_basis": "ecc_absolute_dbu",
                "unsupported_shapes": unsupported,
            },
        }
        for name, items in groups.items()
    ]


def liberty_views(path: Path):
    """Tokenize exported Liberty ports/arcs; retain the raw library for tables."""
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(), flags=re.S)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}():;,]|[^\s{}():;,]+', text)
    stack, ports, global_fields = [], {}, {}
    current_pin = None
    i = 0
    while i < len(tokens):
        name = tokens[i]
        if i + 1 < len(tokens) and tokens[i + 1] == "(":
            end = i + 2
            depth = 1
            while end < len(tokens) and depth:
                depth += (tokens[end] == "(") - (tokens[end] == ")")
                end += 1
            if depth:
                raise ValueError("Unbalanced Liberty group")
            args = " ".join(tokens[i + 2 : end - 1]).strip('"')
            if end < len(tokens) and tokens[end] == "{":
                stack.append((name, current_pin))
                if name == "pin":
                    current_pin = args
                    ports.setdefault(args, {"arcs": []})
                elif name == "timing" and current_pin:
                    ports[current_pin]["arcs"].append({})
                i = end + 1
                continue
        if name == "}":
            if not stack:
                raise ValueError("Unbalanced Liberty closing group")
            _, current_pin = stack.pop()
        elif i + 1 < len(tokens) and tokens[i + 1] == ":":
            end = i + 2
            while end < len(tokens) and tokens[end] != ";":
                end += 1
            value = " ".join(tokens[i + 2 : end]).strip('"')
            if name in {
                "time_unit",
                "voltage_unit",
                "nom_process",
                "nom_temperature",
                "nom_voltage",
            }:
                global_fields[name] = value
            if current_pin and name in {"direction", "clock", "capacitance"}:
                ports[current_pin][name] = value
            if (
                current_pin
                and ports[current_pin]["arcs"]
                and name in {"related_pin", "timing_type", "timing_sense"}
            ):
                ports[current_pin]["arcs"][-1][name] = value
            i = end
        i += 1
    if stack:
        raise ValueError("Unclosed Liberty group")
    return [
        {
            "label": "LIB · ports and timing arcs",
            "kind": "timing_model",
            "items": [
                {"label": name, "pins": [name], "details": details}
                for name, details in ports.items()
            ],
            "summary": {
                **global_fields,
                "ports": len(ports),
                "arcs": sum(len(p["arcs"]) for p in ports.values()),
            },
        }
    ]
