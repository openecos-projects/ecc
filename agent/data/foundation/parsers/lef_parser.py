from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LefPin:
    name: str
    direction: str | None = None
    use: str | None = None
    shapes: list[dict[str, Any]] = field(default_factory=list)
    source: str | None = None


@dataclass(frozen=True)
class LefMacro:
    name: str
    pins: dict[str, LefPin] = field(default_factory=dict)
    source: str | None = None
    size: dict[str, float] | None = None
    macro_class: str | None = None
    site: str | None = None


@dataclass(frozen=True)
class LefLayer:
    name: str
    layer_type: str | None = None
    direction: str | None = None
    pitch: float | None = None
    width: float | None = None
    spacing: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class LefVia:
    name: str
    layers: list[str] = field(default_factory=list)
    rects_by_layer: dict[str, list[dict[str, float]]] = field(default_factory=dict)
    source: str | None = None


@dataclass(frozen=True)
class LefLibrary:
    macros: dict[str, LefMacro] = field(default_factory=dict)
    layers: dict[str, LefLayer] = field(default_factory=dict)
    vias: dict[str, LefVia] = field(default_factory=dict)


_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)")
_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
_END_RE = re.compile(r"^\s*END(?:\s+(\S+))?\s*$")
_DIRECTION_RE = re.compile(r"\bDIRECTION\s+(\S+)\s*;")
_USE_RE = re.compile(r"\bUSE\s+(\S+)\s*;")
_LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;?")
_RECT_RE = re.compile(
    r"\bRECT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*;"
)
_SIZE_RE = re.compile(r"\bSIZE\s+(-?\d+(?:\.\d+)?)\s+BY\s+(-?\d+(?:\.\d+)?)\s*;")
_CLASS_RE = re.compile(r"\bCLASS\s+(\S+)\s*;")
_SITE_RE = re.compile(r"\bSITE\s+(\S+)\s*;")
_TYPE_RE = re.compile(r"\bTYPE\s+(\S+)\s*;")
_PITCH_RE = re.compile(r"\bPITCH\s+(-?\d+(?:\.\d+)?)(?:\s+(-?\d+(?:\.\d+)?))?\s*;")
_WIDTH_RE = re.compile(r"\bWIDTH\s+(-?\d+(?:\.\d+)?)\s*;")
_SPACING_RE = re.compile(r"\bSPACING\s+(-?\d+(?:\.\d+)?)\s*;")
_VIA_RE = re.compile(r"^\s*VIA\s+(\S+)")


def parse_lef(path: Path) -> dict[str, LefMacro]:
    return parse_lef_library(path).macros


def parse_lef_library(path: Path) -> LefLibrary:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return LefLibrary()
    macros: dict[str, LefMacro] = {}
    layers: dict[str, LefLayer] = {}
    vias: dict[str, LefVia] = {}
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        macro_match = _MACRO_RE.match(stripped)
        if macro_match:
            macro, idx = _parse_macro(lines, idx, macro_match.group(1), str(path))
            macros[macro.name] = macro
            continue
        layer_match = _LAYER_RE.match(stripped)
        if layer_match and not stripped.endswith(";"):
            layer, idx = _parse_layer(lines, idx, layer_match.group(1), str(path))
            layers[layer.name] = layer
            continue
        via_match = _VIA_RE.match(stripped)
        if via_match:
            via, idx = _parse_via(lines, idx, via_match.group(1), str(path))
            vias[via.name] = via
            continue
        idx += 1
    return LefLibrary(macros=macros, layers=layers, vias=vias)


def _parse_macro(
    lines: list[str], start: int, macro_name: str, source: str
) -> tuple[LefMacro, int]:
    macro_pins: dict[str, LefPin] = {}
    macro_size: dict[str, float] | None = None
    macro_class: str | None = None
    site: str | None = None
    pin_name: str | None = None
    pin_direction: str | None = None
    pin_use: str | None = None
    pin_shapes: list[dict[str, Any]] = []
    current_layer: str | None = None
    port_index = -1
    idx = start + 1
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        if pin_name is None:
            size_match = _SIZE_RE.search(stripped)
            if size_match:
                macro_size = {
                    "width": float(size_match.group(1)),
                    "height": float(size_match.group(2)),
                }
            class_match = _CLASS_RE.search(stripped)
            if class_match:
                macro_class = class_match.group(1).upper()
            site_match = _SITE_RE.search(stripped)
            if site_match:
                site = site_match.group(1)
            pin_match = _PIN_RE.match(stripped)
            if pin_match:
                pin_name = pin_match.group(1)
                pin_direction = None
                pin_use = None
                pin_shapes = []
                current_layer = None
                port_index = -1
                idx += 1
                continue
            end_match = _END_RE.match(stripped)
            if end_match and end_match.group(1) == macro_name:
                return LefMacro(
                    name=macro_name,
                    pins=macro_pins,
                    source=source,
                    size=macro_size,
                    macro_class=macro_class,
                    site=site,
                ), idx + 1
            idx += 1
            continue

        direction_match = _DIRECTION_RE.search(stripped)
        if direction_match:
            pin_direction = direction_match.group(1).upper()
        use_match = _USE_RE.search(stripped)
        if use_match:
            pin_use = use_match.group(1).upper()
        if stripped == "PORT":
            port_index += 1
            current_layer = None
        layer_match = _LAYER_RE.search(stripped)
        if layer_match:
            current_layer = layer_match.group(1)
        rect_match = _RECT_RE.search(stripped)
        if rect_match and current_layer:
            llx, lly, urx, ury = (float(rect_match.group(i)) for i in range(1, 5))
            pin_shapes.append(
                {
                    "shape_id": len(pin_shapes),
                    "port_index": max(port_index, 0),
                    "layer": current_layer,
                    "shape_type": "rect",
                    "rect": {"llx": llx, "lly": lly, "urx": urx, "ury": ury},
                    "polygon": None,
                    "source": "lef_pin_rect",
                }
            )
        end_match = _END_RE.match(stripped)
        if end_match and end_match.group(1) == pin_name:
            macro_pins[pin_name] = LefPin(
                name=pin_name,
                direction=pin_direction,
                use=pin_use,
                shapes=pin_shapes,
                source=source,
            )
            pin_name = None
            current_layer = None
            port_index = -1
        idx += 1
    return LefMacro(
        name=macro_name,
        pins=macro_pins,
        source=source,
        size=macro_size,
        macro_class=macro_class,
        site=site,
    ), idx


def _parse_layer(lines: list[str], start: int, name: str, source: str) -> tuple[LefLayer, int]:
    layer_type: str | None = None
    direction: str | None = None
    pitch: float | None = None
    width: float | None = None
    spacing: float | None = None
    idx = start + 1
    while idx < len(lines):
        stripped = lines[idx].strip()
        type_match = _TYPE_RE.search(stripped)
        if type_match:
            layer_type = type_match.group(1).lower()
        direction_match = _DIRECTION_RE.search(stripped)
        if direction_match:
            direction = direction_match.group(1).lower()
        pitch_match = _PITCH_RE.search(stripped)
        if pitch_match:
            pitch = float(pitch_match.group(1))
        width_match = _WIDTH_RE.search(stripped)
        if width_match:
            width = float(width_match.group(1))
        spacing_match = _SPACING_RE.search(stripped)
        if spacing_match and spacing is None:
            spacing = float(spacing_match.group(1))
        end_match = _END_RE.match(stripped)
        if end_match and end_match.group(1) == name:
            return LefLayer(
                name=name,
                layer_type=layer_type,
                direction=direction,
                pitch=pitch,
                width=width,
                spacing=spacing,
                source=source,
            ), idx + 1
        idx += 1
    return LefLayer(
        name=name,
        layer_type=layer_type,
        direction=direction,
        pitch=pitch,
        width=width,
        spacing=spacing,
        source=source,
    ), idx


def _parse_via(lines: list[str], start: int, name: str, source: str) -> tuple[LefVia, int]:
    rects_by_layer: dict[str, list[dict[str, float]]] = {}
    current_layer: str | None = None
    idx = start + 1
    while idx < len(lines):
        stripped = lines[idx].strip()
        layer_match = _LAYER_RE.search(stripped)
        if layer_match:
            current_layer = layer_match.group(1)
            rects_by_layer.setdefault(current_layer, [])
        rect_match = _RECT_RE.search(stripped)
        if rect_match and current_layer:
            llx, lly, urx, ury = (float(rect_match.group(i)) for i in range(1, 5))
            rects_by_layer.setdefault(current_layer, []).append(
                {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
            )
        end_match = _END_RE.match(stripped)
        if end_match and end_match.group(1) == name:
            return LefVia(
                name=name, layers=list(rects_by_layer), rects_by_layer=rects_by_layer, source=source
            ), idx + 1
        idx += 1
    return LefVia(
        name=name, layers=list(rects_by_layer), rects_by_layer=rects_by_layer, source=source
    ), idx


def parse_lef_files(paths: list[Path]) -> dict[str, LefMacro]:
    return parse_lef_libraries(paths).macros


def parse_lef_libraries(paths: list[Path]) -> LefLibrary:
    macros: dict[str, LefMacro] = {}
    layers: dict[str, LefLayer] = {}
    vias: dict[str, LefVia] = {}
    for path in paths:
        library = parse_lef_library(path)
        for name, macro in library.macros.items():
            macros.setdefault(name, macro)
        for name, layer in library.layers.items():
            layers.setdefault(name, layer)
        for name, via in library.vias.items():
            vias.setdefault(name, via)
    return LefLibrary(macros=macros, layers=layers, vias=vias)
