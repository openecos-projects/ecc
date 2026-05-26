"""Compatibility alias for renderer registry helpers."""

import sys

from chipcompiler.cli.rendering import renderers as _renderers

sys.modules[__name__] = _renderers
