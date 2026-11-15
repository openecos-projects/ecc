"""Render a restricted declarative primitive mapping, never arbitrary tool code."""

import re
from pathlib import Path

from chipcompiler.pdk.manifest import DescriptorError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRIMITIVE = re.compile(r"^\$_(?:DLATCH_[NP](?:[NP][01])?|TBUF)_$")


def render_primitive_mapping(mappings: list[dict], output: Path) -> None:
    lines = []
    seen = set()
    for mapping in mappings:
        primitive = mapping.get("primitive", "")
        if not _PRIMITIVE.fullmatch(primitive) or primitive in seen:
            raise DescriptorError(
                "invalid_mapping", f"unsupported or duplicate primitive: {primitive}"
            )
        seen.add(primitive)
        ports = ["A", "E", "Y"] if primitive == "$_TBUF_" else ["E", "D", "Q"]
        if len(primitive.split("_")[2]) > 1 and primitive != "$_TBUF_":
            ports.insert(1, "R")
        output_port = ports[-1]
        if primitive == "$_TBUF_":
            lines.extend(
                [
                    '(* techmap_celltype = "\\$_TBUF_" *)',
                    "module _ecc_tbuf_disabled (input A, E, output Y);",
                    "  parameter _TECHMAP_CONSTMSK_E_ = 1'b0;",
                    "  parameter _TECHMAP_CONSTVAL_E_ = 1'bx;",
                    "  wire _TECHMAP_FAIL_ = !(_TECHMAP_CONSTMSK_E_ && !_TECHMAP_CONSTVAL_E_);",
                    '  wire [1023:0] _TECHMAP_DO_ = "connect -unset Y";',
                    "endmodule",
                ]
            )
        lines.extend(
            [
                f"module \\{primitive} ({', '.join(ports)});",
                f"  input {', '.join(ports[:-1])};",
                f"  output {output_port};",
            ]
        )
        instances = mapping.get("instances", [])
        if not instances:
            raise DescriptorError("invalid_mapping", "a primitive mapping requires instances")
        wires = mapping.get("wires", [])
        if any(not _IDENTIFIER.fullmatch(wire) or wire in ports for wire in wires):
            raise DescriptorError("invalid_mapping", "invalid intermediate wire")
        if wires:
            lines.append(f"  wire {', '.join(wires)};")
        for index, instance in enumerate(instances):
            master = instance.get("master", "")
            pins = instance.get("pins", {})
            if not _IDENTIFIER.fullmatch(master) or not pins:
                raise DescriptorError("invalid_mapping", "invalid cell master or pin mapping")
            for pin, signal in pins.items():
                if not _IDENTIFIER.fullmatch(pin) or signal not in [*ports, *wires]:
                    raise DescriptorError("invalid_mapping", f"invalid pin connection: {pin}")
            connections = ", ".join(f".{pin}({signal})" for pin, signal in pins.items())
            lines.append(f"  {master} mapped_{index} ({connections});")
        lines.append("endmodule")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
