"""Compatibility alias for core output helpers."""

import sys

from chipcompiler.cli.core import output as _output

sys.modules[__name__] = _output
