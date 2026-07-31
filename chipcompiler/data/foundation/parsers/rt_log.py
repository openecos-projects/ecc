from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_LAYER_RE = re.compile(
    r"idx:(\d+)\s+order:(\d+)\s+name:(\S+)\s+prefer_direction:(horizontal|vertical)", re.IGNORECASE
)
_TOTAL_RE = re.compile(r"\|\s*(total_[a-z_]+)\s*\|\s*(-?\d+(?:\.\d+)?)\s*\|", re.IGNORECASE)


def parse_rt_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "layers": [], "totals": {}, "source": str(path)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"available": False, "layers": [], "totals": {}, "source": str(path)}
    layers = []
    totals: dict[str, float] = {}
    for line in text.splitlines():
        layer_match = _LAYER_RE.search(line)
        if layer_match:
            layers.append(
                {
                    "id": int(layer_match.group(1)),
                    "order": int(layer_match.group(2)),
                    "name": layer_match.group(3),
                    "preferred_direction": layer_match.group(4).lower(),
                    "source": "rt_log",
                }
            )
        for total_match in _TOTAL_RE.finditer(line):
            totals[total_match.group(1).lower()] = float(total_match.group(2))
    return {"available": True, "layers": layers, "totals": totals, "source": str(path)}
