"""Compatibility alias for core record helpers."""

import sys

from chipcompiler.cli.core import records as _records

sys.modules[__name__] = _records
