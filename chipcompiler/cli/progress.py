"""Compatibility alias for progress render helpers."""

import sys

from chipcompiler.cli.rendering import progress as _progress

sys.modules[__name__] = _progress
