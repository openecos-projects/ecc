"""Compatibility alias for diagnose inspection helpers."""

import sys

from chipcompiler.cli.inspection import diagnose as _diagnose

sys.modules[__name__] = _diagnose
