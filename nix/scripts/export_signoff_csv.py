#!/usr/bin/env python3
"""CI/lit entry → test.lit csv_gates (not product ecc signoff)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_LIT = _REPO / "test" / "lit"
if str(_LIT) not in sys.path:
    sys.path.insert(0, str(_LIT))

from csv_gates.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
