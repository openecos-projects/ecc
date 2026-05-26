"""Compatibility alias for inspection discovery helpers."""

import sys

from chipcompiler.cli.inspection import discovery as _discovery

sys.modules[__name__] = _discovery
