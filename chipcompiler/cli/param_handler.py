"""Compatibility alias for parameter command handlers."""

import sys

from chipcompiler.cli.handlers import param as _param

sys.modules[__name__] = _param
