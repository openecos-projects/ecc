"""Compatibility alias for core command types."""

import sys

from chipcompiler.cli.core import types as _types

sys.modules[__name__] = _types
