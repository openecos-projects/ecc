from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_gcell_info(path: Path) -> list[dict[str, Any]]:
    """Parse iRT early-router gcell.info rows.

    iRT writes rows as ``x,y,llx,lly,urx,ury``.  The returned order preserves
    file order, but consumers should use the explicit x/y indices.
    """
    cells: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        stripped = line.strip().rstrip(",")
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split(",") if part.strip()]
        if len(parts) < 6:
            continue
        try:
            x = int(float(parts[0]))
            y = int(float(parts[1]))
            llx = float(parts[2])
            lly = float(parts[3])
            urx = float(parts[4])
            ury = float(parts[5])
        except ValueError:
            continue
        if urx <= llx or ury <= lly:
            continue
        cells.append({"x": x, "y": y, "bbox": {"llx": llx, "lly": lly, "urx": urx, "ury": ury}})
    return cells
