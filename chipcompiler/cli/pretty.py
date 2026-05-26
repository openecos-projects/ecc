"""Compatibility alias for pretty render helpers."""

import sys

from chipcompiler.cli.rendering import pretty as _pretty

sys.modules[__name__] = _pretty
