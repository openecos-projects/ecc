"""Compatibility alias for core option definitions."""

import sys

from chipcompiler.cli.core import options as _options

sys.modules[__name__] = _options
