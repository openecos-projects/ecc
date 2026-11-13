#!/usr/bin/env python
"""Prepare netlists for the kepler-formal comparison.

kepler-formal reads plain Verilog and requires every instantiated cell to be
modeled by the loaded Liberty libraries. Two gap-filling transforms live here:

- gzip decompression: physical steps emit ``.v.gz`` netlists; kepler-formal
  has no compressed-input support.
- physical-cell stripping: FILLER/FILLTAP/FILLCAP instances are inserted
  during implementation, carry no function model in Liberty, and would abort
  netlist loading. Removing them is standard LEC practice; the reference
  (golden) side never contains them.
- empty port-connection stripping: ``.PIN()`` leaves a port unconnected, but
  kepler-formal rejects it when the Liberty model does not declare that pin
  (common on power/ground pad cells). Removing the explicit empty connection
  is semantically identical to omitting it.
- supply-connection stripping: implementation netlists often connect a
  standard cell's ``.VDD(VDD)/.VSS(VSS)`` supply pins, which Liberty models as
  ``pg_pin`` rather than connectable ports. A connection is removed only when
  Liberty declares that pin as a ``pg_pin`` on the instantiated master and the
  connected net is ``VDD`` or ``VSS``. Ordinary module ports with supply-like
  names, and real power-pad pins such as ``.VDD1(PLL_AVDD)``, stay intact. The
  supply transform is applied symmetrically to golden and gate netlists because
  either side may contain the same cell-level supply connectivities.

Digests for the result contract are always taken on the ORIGINAL inputs, so
stale-proof checks stay meaningful; only the YAML handed to kepler-formal
points at the prepared copies.
"""

import gzip
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

# Industry-conventional physical-only tokens; they cover the PDK filler lists
# (FILLER<width>...), prefixed IO fillers (P65_1233_FILLER50), IO corners
# (P65_1233_CORNER), plus tap and decap cells that no Liberty models.
_PHYSICAL_CELL_PREFIXES = ("FILLER", "FILLTAP", "FILLCAP", "CORNER")

_INSTANCE_LINE = r"^\s*(?:%s)\S*\s+\\?\S+\s*\([^;]*\)\s*;[ \t]*$"

# These patterns target instance text in netlists prepared for LEC. String and
# comment literals are not semantic inputs to the comparison, but callers
# should keep the transforms narrowly scoped if these files gain another use.
_EMPTY_PORT = r"\.\s*[A-Za-z_]\w*\s*\(\s*\)"
_SUPPLY_NET = r"(?:VDD|VSS)"
_CELL_GROUP = re.compile(r"\bcell\s*\(\s*([^)]+?)\s*\)\s*\{")
_PG_PIN_GROUP = re.compile(r"\bpg_pin\s*\(\s*([^)]+?)\s*\)\s*\{")
_VERILOG_INSTANCE = re.compile(
    r"\b(?P<master>[A-Za-z_][A-Za-z0-9_$]*)\s+"
    r"(?:#\s*\([^;]*?\)\s*)?"
    r"(?P<instance>\\?\S+)\s*"
    r"\((?P<connections>[^;]*?)\)\s*;"
)


def physical_cell_names(pdk) -> set[str]:
    """Explicit physical-cell masters declared by the workspace PDK."""
    names = set()
    for attr in ("fillers",):
        values = getattr(pdk, attr, None) or []
        names.update(str(value) for value in values)
    for attr in ("tap_cell", "end_cap"):
        value = getattr(pdk, attr, None)
        if value:
            names.add(str(value))
    return names


def _without_liberty_comments(text: str) -> str:
    """Remove Liberty comments while retaining quoted strings."""
    result = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _group_end(text: str, open_brace: int) -> int:
    depth = 1
    in_string = False
    escaped = False
    for index in range(open_brace + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _cell_bodies(text: str):
    for match in _CELL_GROUP.finditer(text):
        body_start = match.end()
        body_end = _group_end(text, body_start - 1)
        if body_end < 0:
            continue
        yield match.group(1).strip().strip('"'), text[body_start:body_end]


@lru_cache(maxsize=8)
def _cached_liberty_supply_pins(
    paths: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    cells: dict[str, set[str]] = {}
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for cell, body in _cell_bodies(_without_liberty_comments(text)):
            pins = {match.group(1).strip().strip('"') for match in _PG_PIN_GROUP.finditer(body)}
            if pins:
                cells.setdefault(cell, set()).update(pins)
    return tuple((cell, tuple(sorted(pins))) for cell, pins in sorted(cells.items()))


def liberty_supply_pins(paths: Iterable[str | Path] | None) -> dict[str, set[str]]:
    """Map each Liberty cell to the pins explicitly declared as ``pg_pin``."""
    normalized = tuple(str(Path(path)) for path in paths or () if path)
    return {cell: set(pins) for cell, pins in _cached_liberty_supply_pins(normalized)}


def _strip_pattern(physical_cells: set[str]) -> re.Pattern:
    """Instance-line pattern for the given masters plus prefix fallbacks."""
    masters = sorted(
        name for name in physical_cells if not name.startswith(_PHYSICAL_CELL_PREFIXES)
    )
    # A leading ``name_`` segment admits PDK-prefixed physical cells such as
    # ``P65_1233_FILLER50`` without matching unrelated functional names.
    prefixes = [f"[A-Za-z0-9_$]*_{prefix}\\S*|{prefix}\\S*" for prefix in _PHYSICAL_CELL_PREFIXES]
    alternatives = [*(re.escape(name) for name in masters), *prefixes]
    return re.compile(_INSTANCE_LINE % "|".join(alternatives), re.MULTILINE)


def _strip_connections(text: str, connection: str) -> tuple[str, int]:
    """Remove named-port connections, keeping the surrounding comma valid.

    The transforms are ordered so a comma belongs to exactly one side of the
    removed connection; the remaining whitespace is collapsed only where the
    connection itself was removed.
    """
    count = 0
    for pattern in (
        re.compile(rf",\s*(?:{connection})"),
        re.compile(rf"(?:{connection})\s*,\s*"),
        re.compile(rf"(?:{connection})\s*(?=\))"),
    ):
        text, replacements = pattern.subn("", text)
        count += replacements
    return text, count


def _strip_supply_connections(text: str, supply_pins: Mapping[str, set[str]]) -> tuple[str, int]:
    if not supply_pins:
        return text, 0
    count = 0

    def replace(match: re.Match) -> str:
        nonlocal count
        pins = supply_pins.get(match.group("master"))
        if not pins:
            return match.group(0)
        alternatives = "|".join(re.escape(pin) for pin in sorted(pins))
        connection = rf"\.\s*(?:{alternatives})\s*\(\s*{_SUPPLY_NET}\s*\)"
        connections, removed = _strip_connections(match.group("connections"), connection)
        if removed == 0:
            return match.group(0)
        count += removed
        original = match.group(0)
        start = match.start("connections") - match.start()
        end = match.end("connections") - match.start()
        return original[:start] + connections + original[end:]

    return _VERILOG_INSTANCE.sub(replace, text), count


def prepare_netlist(
    source: Path | str,
    target: Path | str,
    physical_cells: set[str],
    supply_pins: Mapping[str, set[str]] | None = None,
) -> Path:
    """Return a kepler-formal-readable path for *source*, writing *target* only
    when a transform (decompression, physical-cell strip, or empty-port strip)
    is needed."""
    source = Path(source)
    target = Path(target)

    text = None
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()

    if text is None:
        text = source.read_text(encoding="utf-8", errors="ignore")

    stripped, physical_count = _strip_pattern(physical_cells).subn("", text)
    stripped, empty_port_count = _strip_connections(stripped, _EMPTY_PORT)
    stripped, supply_count = _strip_supply_connections(stripped, supply_pins or {})
    if (
        physical_count == 0
        and empty_port_count == 0
        and supply_count == 0
        and source.suffix != ".gz"
    ):
        return source

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stripped, encoding="utf-8")
    return target
