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

Digests for the result contract are always taken on the ORIGINAL inputs, so
stale-proof checks stay meaningful; only the YAML handed to kepler-formal
points at the prepared copies.
"""

import gzip
import re
from pathlib import Path

# Industry-conventional physical-only prefixes; they cover the PDK filler
# lists (FILLER<width>...) plus tap and decap cells that no Liberty models.
_PHYSICAL_CELL_PREFIXES = ("FILLER", "FILLTAP", "FILLCAP")

_INSTANCE_LINE = r"^\s*(?:%s)\S*\s+\\?\S+\s*\([^;]*\)\s*;[ \t]*$"


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
    prefixes = [f"{prefix}\\S*" for prefix in _PHYSICAL_CELL_PREFIXES]
    alternatives = [*(re.escape(name) for name in masters), *prefixes]
    return re.compile(_INSTANCE_LINE % "|".join(alternatives), re.MULTILINE)


def prepare_netlist(source: Path | str, target: Path | str, physical_cells: set[str]) -> Path:
    """Return a kepler-formal-readable path for *source*, writing *target* only
    when a transform (decompression and/or physical-cell strip) is needed."""
    source = Path(source)
    target = Path(target)

    text = None
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()

    pattern = _strip_pattern(physical_cells)
    if text is None:
        text = source.read_text(encoding="utf-8", errors="ignore")
        if not pattern.search(text):
            return source

    stripped, count = pattern.subn("", text)
    if count == 0 and source.suffix != ".gz":
        return source

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stripped, encoding="utf-8")
    return target
