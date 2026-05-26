"""Compatibility alias for param command registration."""

import sys

from chipcompiler.cli.commands import param as _param

sys.modules[__name__] = _param
