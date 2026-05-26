"""Compatibility alias for render helpers."""

import sys

from chipcompiler.cli.rendering import render as _render

sys.modules[__name__] = _render
