"""Adapters for electrical and deliverable results with explicit source units."""

import hashlib
import json
from pathlib import Path

from chipcompiler.tools.ecc.metrics import (
    _SPEF_CAPACITANCE_UNIT_TO_FF,
    _SPEF_RESISTANCE_UNIT_TO_OHM,
    _spef_entry_value,
    _spef_unit_scale,
)


def rcx(path: Path):
    names, items = {}, []
    cap_scale = res_scale = None
    section, current = "", None
    with path.open() as stream:
        for line in stream:
            tokens = line.split()
            if not tokens:
                continue
            directive = tokens[0]
            if directive == "*NAME_MAP":
                section = "names"
            elif directive == "*C_UNIT":
                cap_scale = _spef_unit_scale(tokens, _SPEF_CAPACITANCE_UNIT_TO_FF)
            elif directive == "*R_UNIT":
                res_scale = _spef_unit_scale(tokens, _SPEF_RESISTANCE_UNIT_TO_OHM)
            elif directive == "*D_NET":
                total = _spef_entry_value(tokens)
                if total is None or cap_scale is None:
                    raise ValueError("Missing valid SPEF capacitance units or net value")
                name = names.get(tokens[1], tokens[1])
                current = {
                    "label": name,
                    "nets": [name],
                    "value": total * cap_scale,
                    "details": {"capacitance_ff": total * cap_scale, "resistance_sum_ohm": 0.0},
                }
                items.append(current)
                section = ""
            elif directive == "*RES":
                section = "res"
            elif directive == "*END":
                current, section = None, ""
            elif section == "names" and directive.startswith("*") and directive[1:].isdigit():
                names[directive] = " ".join(tokens[1:])
            elif directive.startswith("*"):
                section = ""
            elif section == "res" and current is not None:
                resistance = _spef_entry_value(tokens)
                if resistance is None or res_scale is None:
                    raise ValueError("Missing valid SPEF resistance units or value")
                current["details"]["resistance_sum_ohm"] += resistance * res_scale
    return [
        {
            "label": f"{path.stem} · net capacitance",
            "kind": "rcx",
            "unit": "fF",
            "items": items,
            "summary": {
                "reported_nets": len(items),
                "resistance_note": "Sum of segments; not effective path resistance",
            },
        }
    ]


def formal(path: Path):
    payload = json.loads(path.read_text())
    # Native events carry structured status/coverage; engine-neutral results bind
    # the compared inputs and retain the existing authoritative proven verdict.
    summary = payload.get("metrics", payload)
    return [{"label": "Equivalence result", "kind": "formal", "items": [], "summary": summary}]


def deliverables(step, started_unix_ns):
    items = []
    for kind in ("lef", "lib", "gds"):
        value = getattr(step.output, kind, None)
        if not value:
            continue
        path = Path(value)
        if path.is_file() and path.stat().st_mtime_ns >= started_unix_ns:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            items.append(
                {
                    "label": path.name,
                    "details": {"kind": kind, "size": path.stat().st_size, "sha256": digest},
                }
            )
    return {
        "label": "Harden deliverables",
        "kind": "artifacts",
        "basis": "final",
        "items": items,
        "summary": {"artifacts": [item["details"] | {"file": item["label"]} for item in items]},
    }
