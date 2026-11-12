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
  ``pg_pin`` rather than connectable ports. Only connections whose port and
  net are both ``VDD`` or ``VSS`` are removed, so real power-pad pins such as
  ``.VDD1(PLL_AVDD)`` or ``.VDD(PLL_DVDD)`` stay intact.

Digests for the result contract are always taken on the ORIGINAL inputs, so
stale-proof checks stay meaningful; only the YAML handed to kepler-formal
points at the prepared copies.
"""

import gzip
import re
from pathlib import Path

# Industry-conventional physical-only tokens; they cover the PDK filler lists
# (FILLER<width>...), prefixed IO fillers (P65_1233_FILLER50), IO corners
# (P65_1233_CORNER), plus tap and decap cells that no Liberty models.
_PHYSICAL_CELL_PREFIXES = ("FILLER", "FILLTAP", "FILLCAP", "CORNER")

_INSTANCE_LINE = r"^\s*(?:%s)\S*\s+\\?\S+\s*\([^;]*\)\s*;[ \t]*$"

_EMPTY_PORT = r"\.\s*[A-Za-z_]\w*\s*\(\s*\)"
_SUPPLY_CONNECTION = r"\.\s*(?:VDD|VSS)\s*\(\s*(?:VDD|VSS)\s*\)"


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


def prepare_netlist(source: Path | str, target: Path | str, physical_cells: set[str]) -> Path:
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
    stripped, supply_count = _strip_connections(stripped, _SUPPLY_CONNECTION)
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
