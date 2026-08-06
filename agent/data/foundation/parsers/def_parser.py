from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DefTrack:
    axis: str
    start: float
    count: int
    step: float
    layer: str


@dataclass(frozen=True)
class DefRow:
    name: str
    site: str
    x: float
    y: float
    orient: str
    count_x: int
    count_y: int
    step_x: float
    step_y: float


@dataclass(frozen=True)
class DefWire:
    net: str
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float | None = None
    via: str | None = None
    special: bool = False

    @property
    def length(self) -> float:
        return abs(self.x2 - self.x1) + abs(self.y2 - self.y1)

    @property
    def direction(self) -> str:
        if abs(self.x2 - self.x1) >= abs(self.y2 - self.y1):
            return "horizontal"
        return "vertical"


@dataclass(frozen=True)
class DefNet:
    name: str
    pins: list[dict[str, Any]] = field(default_factory=list)
    wires: list[DefWire] = field(default_factory=list)
    special: bool = False
    use: str | None = None


@dataclass(frozen=True)
class DefData:
    path: Path
    units: int | None
    diearea: dict[str, float] | None
    gcell_x: list[float]
    gcell_y: list[float]
    rows: list[DefRow]
    tracks: list[DefTrack]
    vias: list[dict[str, Any]]
    components: list[dict[str, Any]]
    pins: list[dict[str, Any]]
    nets: list[DefNet]


_COMPONENT_RE = re.compile(r"^\s*-\s+(\S+)\s+(\S+)(.*)")
_PLACED_RE = re.compile(
    r"\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+(\S+)"
)
_PIN_RE = re.compile(r"\(\s+(\S+)\s+(\S+)\s+\)")
_POINT_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?|\*)\s+(-?\d+(?:\.\d+)?|\*)\s+\)")


def parse_def(path: Path) -> DefData:
    parsed = _parse_def_lines(_iter_def_lines(path))
    return DefData(
        path=path,
        units=parsed["units"],
        diearea=parsed["diearea"],
        gcell_x=parsed["gcell_x"],
        gcell_y=parsed["gcell_y"],
        rows=parsed["rows"],
        tracks=parsed["tracks"],
        vias=parsed["vias"],
        components=parsed["components"],
        pins=parsed["pins"],
        nets=parsed["nets"],
    )


def _iter_def_lines(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield line.rstrip()
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            yield line.rstrip()


def _parse_def_lines(lines) -> dict[str, Any]:
    result: dict[str, Any] = {
        "units": None,
        "diearea": None,
        "gcell_x": [],
        "gcell_y": [],
        "rows": [],
        "tracks": [],
        "vias": [],
        "components": [],
        "pins": [],
        "nets": [],
    }
    section: str | None = None
    current_via: dict[str, Any] | None = None
    current_via_layer: str | None = None
    current_pin: dict[str, Any] | None = None
    current_net_name = ""
    current_net_chunks: list[str] = []
    current_net_special = False

    def flush_via() -> None:
        nonlocal current_via, current_via_layer
        if current_via:
            result["vias"].append(current_via)
        current_via = None
        current_via_layer = None

    def flush_pin() -> None:
        nonlocal current_pin
        if current_pin:
            result["pins"].append(current_pin)
        current_pin = None

    def flush_net() -> None:
        nonlocal current_net_name, current_net_chunks
        if current_net_name:
            result["nets"].append(
                _net_from_chunks(current_net_name, current_net_chunks, special=current_net_special)
            )
        current_net_name = ""
        current_net_chunks = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if section is None:
            units_match = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", stripped)
            if units_match:
                result["units"] = int(units_match.group(1))
            diearea_match = re.search(
                r"DIEAREA\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
                stripped,
            )
            if diearea_match:
                llx, lly, urx, ury = (float(diearea_match.group(i)) for i in range(1, 5))
                result["diearea"] = {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
            gcell_match = re.search(
                r"GCELLGRID\s+([XY])\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)",
                stripped,
            )
            if gcell_match:
                axis = gcell_match.group(1)
                values = result["gcell_x"] if axis == "X" else result["gcell_y"]
                start = float(gcell_match.group(2))
                count = int(gcell_match.group(3))
                step = float(gcell_match.group(4))
                for idx in range(count):
                    value = start + idx * step
                    if not values or value > values[-1]:
                        values.append(value)
            track_match = re.search(
                r"TRACKS\s+([XY])\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+LAYER\s+(\S+)",
                stripped,
            )
            if track_match:
                result["tracks"].append(
                    DefTrack(
                        axis=track_match.group(1),
                        start=float(track_match.group(2)),
                        count=int(track_match.group(3)),
                        step=float(track_match.group(4)),
                        layer=track_match.group(5),
                    )
                )
            row_match = re.search(
                r"ROW\s+(\S+)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
                stripped,
            )
            if row_match:
                result["rows"].append(
                    DefRow(
                        name=row_match.group(1),
                        site=row_match.group(2),
                        x=float(row_match.group(3)),
                        y=float(row_match.group(4)),
                        orient=row_match.group(5),
                        count_x=int(row_match.group(6)),
                        count_y=int(row_match.group(7)),
                        step_x=float(row_match.group(8)),
                        step_y=float(row_match.group(9)),
                    )
                )
            for candidate in ("VIAS", "COMPONENTS", "PINS", "NETS", "SPECIALNETS"):
                if stripped.startswith(f"{candidate} "):
                    section = candidate
                    current_net_special = candidate == "SPECIALNETS"
                    break
            continue

        if section == "VIAS":
            if stripped.startswith("END VIAS"):
                flush_via()
                section = None
                continue
            if stripped.startswith("- "):
                flush_via()
                tokens = stripped.split()
                layers = []
                if "+ LAYERS" in stripped:
                    layers = stripped.split("+ LAYERS", 1)[1].replace(";", "").split()[:3]
                current_via = {
                    "name": tokens[1],
                    "layers": layers,
                    "rects_by_layer": {},
                    "source": "def_vias",
                }
                current_via_layer = None
                continue
            if current_via is None:
                continue
            layer_match = re.search(r"\+\s+LAYER\s+(\S+)", stripped) or re.match(
                r"LAYER\s+(\S+)", stripped
            )
            if layer_match:
                current_via_layer = layer_match.group(1)
                current_via.setdefault("rects_by_layer", {}).setdefault(current_via_layer, [])
                if current_via_layer not in current_via.setdefault("layers", []):
                    current_via["layers"].append(current_via_layer)
            rect_match = re.search(
                r"RECT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
                stripped,
            )
            if rect_match and current_via_layer:
                llx, lly, urx, ury = (float(rect_match.group(i)) for i in range(1, 5))
                current_via.setdefault("rects_by_layer", {}).setdefault(
                    current_via_layer, []
                ).append({"llx": llx, "lly": lly, "urx": urx, "ury": ury})
            continue

        if section == "COMPONENTS":
            if stripped.startswith("END COMPONENTS"):
                section = None
                continue
            match = _COMPONENT_RE.match(line)
            if match:
                name, master, rest = match.groups()
                placed = _PLACED_RE.search(rest)
                result["components"].append(
                    {
                        "name": name,
                        "master": master,
                        "origin": {"x": float(placed.group(1)), "y": float(placed.group(2))}
                        if placed
                        else None,
                        "orientation": placed.group(3) if placed else None,
                        "source": "def_components",
                    }
                )
            continue

        if section == "PINS":
            if stripped.startswith("END PINS"):
                flush_pin()
                section = None
                continue
            if stripped.startswith("- "):
                flush_pin()
                tokens = stripped.split()
                current_pin = {
                    "pin_name": tokens[1],
                    "instance": "PIN",
                    "source": "def_pins",
                    "def_index": len(result["pins"]),
                    "shapes": [],
                }
            if current_pin is None:
                continue
            net_match = re.search(r"\+\s+NET\s+(\S+)", stripped)
            if net_match:
                current_pin["net"] = net_match.group(1)
            direction_match = re.search(r"\+\s+DIRECTION\s+(\S+)", stripped)
            if direction_match:
                current_pin["direction"] = direction_match.group(1)
            use_match = re.search(r"\+\s+USE\s+(\S+)", stripped)
            if use_match:
                current_pin["use"] = use_match.group(1)
            layer_match = re.search(
                r"\+\s+LAYER\s+(\S+)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
                stripped,
            )
            if layer_match:
                llx, lly, urx, ury = (float(layer_match.group(i)) for i in range(2, 6))
                current_pin.setdefault("shapes", []).append(
                    {
                        "layer": layer_match.group(1),
                        "rect": {"llx": llx, "lly": lly, "urx": urx, "ury": ury},
                        "source": "def_pin_layer_rect",
                    }
                )
            placed = _PLACED_RE.search(stripped)
            if placed:
                current_pin["origin"] = {"x": float(placed.group(1)), "y": float(placed.group(2))}
                current_pin["orientation"] = placed.group(3)
            continue

        if section in {"NETS", "SPECIALNETS"}:
            if stripped.startswith(f"END {section}"):
                flush_net()
                section = None
                continue
            if stripped.startswith("- "):
                flush_net()
                parts = stripped.split(maxsplit=2)
                current_net_name = parts[1]
                current_net_chunks = [parts[2] if len(parts) > 2 else ""]
            elif current_net_name:
                current_net_chunks.append(stripped)

    flush_via()
    flush_pin()
    flush_net()
    return result


def _parse_units(lines: list[str]) -> int | None:
    for line in lines:
        match = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _parse_diearea(lines: list[str]) -> dict[str, float] | None:
    for line in lines:
        match = re.search(
            r"DIEAREA\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
            line,
        )
        if match:
            llx, lly, urx, ury = (float(match.group(i)) for i in range(1, 5))
            return {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
    return None


def _parse_gcell_axis(lines: list[str], axis: str) -> list[float]:
    values: list[float] = []
    for line in lines:
        match = re.search(
            rf"GCELLGRID\s+{axis}\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)", line
        )
        if not match:
            continue
        start = float(match.group(1))
        count = int(match.group(2))
        step = float(match.group(3))
        for idx in range(count):
            value = start + idx * step
            if not values or value > values[-1]:
                values.append(value)
    return values


def _parse_tracks(lines: list[str]) -> list[DefTrack]:
    tracks: list[DefTrack] = []
    for line in lines:
        match = re.search(
            r"TRACKS\s+([XY])\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+LAYER\s+(\S+)",
            line,
        )
        if match:
            tracks.append(
                DefTrack(
                    axis=match.group(1),
                    start=float(match.group(2)),
                    count=int(match.group(3)),
                    step=float(match.group(4)),
                    layer=match.group(5),
                )
            )
    return tracks


def _parse_rows(lines: list[str]) -> list[DefRow]:
    rows: list[DefRow] = []
    for line in lines:
        match = re.search(
            r"ROW\s+(\S+)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
            line,
        )
        if match:
            rows.append(
                DefRow(
                    name=match.group(1),
                    site=match.group(2),
                    x=float(match.group(3)),
                    y=float(match.group(4)),
                    orient=match.group(5),
                    count_x=int(match.group(6)),
                    count_y=int(match.group(7)),
                    step_x=float(match.group(8)),
                    step_y=float(match.group(9)),
                )
            )
    return rows


def _parse_vias(lines: list[str]) -> list[dict[str, Any]]:
    vias: list[dict[str, Any]] = []
    in_vias = False
    current: dict[str, Any] | None = None
    current_layer: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("VIAS "):
            in_vias = True
            continue
        if in_vias and stripped.startswith("END VIAS"):
            if current:
                vias.append(current)
            break
        if not in_vias:
            continue
        if stripped.startswith("- "):
            if current:
                vias.append(current)
            tokens = stripped.split()
            layers = []
            if "+ LAYERS" in stripped:
                layers = stripped.split("+ LAYERS", 1)[1].replace(";", "").split()[:3]
            current = {
                "name": tokens[1],
                "layers": layers,
                "rects_by_layer": {},
                "source": "def_vias",
            }
            current_layer = None
            continue
        if current is None:
            continue
        layer_match = re.search(r"\+\s+LAYER\s+(\S+)", stripped) or re.match(
            r"LAYER\s+(\S+)", stripped
        )
        if layer_match:
            current_layer = layer_match.group(1)
            current.setdefault("rects_by_layer", {}).setdefault(current_layer, [])
            if current_layer not in current.setdefault("layers", []):
                current["layers"].append(current_layer)
        rect_match = re.search(
            r"RECT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
            stripped,
        )
        if rect_match and current_layer:
            llx, lly, urx, ury = (float(rect_match.group(i)) for i in range(1, 5))
            current.setdefault("rects_by_layer", {}).setdefault(current_layer, []).append(
                {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
            )
    return vias


def _parse_components(lines: list[str]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    in_components = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("COMPONENTS "):
            in_components = True
            continue
        if in_components and stripped.startswith("END COMPONENTS"):
            break
        if not in_components:
            continue
        match = _COMPONENT_RE.match(line)
        if not match:
            continue
        name, master, rest = match.groups()
        placed = _PLACED_RE.search(rest)
        components.append(
            {
                "name": name,
                "master": master,
                "origin": {"x": float(placed.group(1)), "y": float(placed.group(2))}
                if placed
                else None,
                "orientation": placed.group(3) if placed else None,
                "source": "def_components",
            }
        )
    return components


def _parse_pins(lines: list[str]) -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    in_pins = False
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("PINS "):
            in_pins = True
            continue
        if in_pins and stripped.startswith("END PINS"):
            if current:
                pins.append(current)
            break
        if not in_pins:
            continue
        if stripped.startswith("- "):
            if current:
                pins.append(current)
            tokens = stripped.split()
            current = {
                "pin_name": tokens[1],
                "instance": "PIN",
                "source": "def_pins",
                "def_index": len(pins),
                "shapes": [],
            }
        if current is None:
            continue
        net_match = re.search(r"\+\s+NET\s+(\S+)", stripped)
        if net_match:
            current["net"] = net_match.group(1)
        direction_match = re.search(r"\+\s+DIRECTION\s+(\S+)", stripped)
        if direction_match:
            current["direction"] = direction_match.group(1)
        use_match = re.search(r"\+\s+USE\s+(\S+)", stripped)
        if use_match:
            current["use"] = use_match.group(1)
        layer_match = re.search(
            r"\+\s+LAYER\s+(\S+)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
            stripped,
        )
        if layer_match:
            llx, lly, urx, ury = (float(layer_match.group(i)) for i in range(2, 6))
            current.setdefault("shapes", []).append(
                {
                    "layer": layer_match.group(1),
                    "rect": {"llx": llx, "lly": lly, "urx": urx, "ury": ury},
                    "source": "def_pin_layer_rect",
                }
            )
        placed = _PLACED_RE.search(stripped)
        if placed:
            current["origin"] = {"x": float(placed.group(1)), "y": float(placed.group(2))}
            current["orientation"] = placed.group(3)
    return pins


def _parse_nets(lines: list[str], section: str, *, special: bool) -> list[DefNet]:
    nets: list[DefNet] = []
    in_section = False
    current_name = ""
    current_chunks: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{section} "):
            in_section = True
            continue
        if in_section and stripped.startswith(f"END {section}"):
            if current_name:
                nets.append(_net_from_chunks(current_name, current_chunks, special=special))
            break
        if not in_section:
            continue
        if stripped.startswith("- "):
            if current_name:
                nets.append(_net_from_chunks(current_name, current_chunks, special=special))
            parts = stripped.split(maxsplit=2)
            current_name = parts[1]
            current_chunks = [parts[2] if len(parts) > 2 else ""]
        elif current_name:
            current_chunks.append(stripped)
    return nets


def _net_from_chunks(name: str, chunks: list[str], *, special: bool) -> DefNet:
    text = " ".join(chunks)
    connection_text = re.split(r"\+\s+(?:ROUTED|FIXED|COVER|NEW)\b", text, maxsplit=1)[0]
    pins = [
        {"instance": inst, "pin_name": pin, "net": name, "source": "def_net_connections"}
        for inst, pin in _PIN_RE.findall(connection_text)
        if not _looks_numeric(inst) and not _looks_numeric(pin) and "*" not in {inst, pin}
    ]
    wires = _parse_routed_wires(name, text, special=special)
    use_match = re.search(r"\+\s+USE\s+(\S+)", text)
    return DefNet(
        name=name,
        pins=pins,
        wires=wires,
        special=special,
        use=use_match.group(1) if use_match else None,
    )


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _parse_routed_wires(net_name: str, text: str, *, special: bool) -> list[DefWire]:
    wires: list[DefWire] = []
    tokens = re.split(r"\b(?:ROUTED|NEW)\b", text)
    for chunk in tokens[1:]:
        parts = chunk.strip().rstrip(";")
        if not parts:
            continue
        layer_match = re.match(r"(\S+)(?:\s+(\d+(?:\.\d+)?))?", parts)
        if not layer_match:
            continue
        layer = layer_match.group(1)
        width = float(layer_match.group(2)) if layer_match.group(2) else None
        points = _POINT_RE.findall(parts)
        if not points:
            continue
        via = _extract_via(parts, points[-1])
        previous: tuple[float, float] | None = None
        for raw_x, raw_y in points:
            if previous is None:
                if raw_x == "*" or raw_y == "*":
                    continue
                previous = (float(raw_x), float(raw_y))
                continue
            x = previous[0] if raw_x == "*" else float(raw_x)
            y = previous[1] if raw_y == "*" else float(raw_y)
            if (x, y) != previous:
                wires.append(
                    DefWire(
                        net=net_name,
                        layer=layer,
                        x1=previous[0],
                        y1=previous[1],
                        x2=x,
                        y2=y,
                        width=width,
                        special=special,
                    )
                )
            previous = (x, y)
        if via:
            via_point = previous
            if via_point is None and points:
                raw_x, raw_y = points[-1]
                if raw_x != "*" and raw_y != "*":
                    via_point = (float(raw_x), float(raw_y))
            if via_point is not None:
                wires.append(
                    DefWire(
                        net=net_name,
                        layer=layer,
                        x1=via_point[0],
                        y1=via_point[1],
                        x2=via_point[0],
                        y2=via_point[1],
                        width=width,
                        via=via,
                        special=special,
                    )
                )
    return wires


def _extract_via(chunk: str, last_point: tuple[str, str]) -> str | None:
    point_pattern = (
        r"\(\s*" + re.escape(last_point[0]) + r"\s+" + re.escape(last_point[1]) + r"\s*\)"
    )
    parts = re.split(point_pattern, chunk, maxsplit=1)
    tail = parts[-1] if len(parts) > 1 else chunk
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_.$-]*\b", tail):
        if "VIA" in token.upper():
            return token
    return None
