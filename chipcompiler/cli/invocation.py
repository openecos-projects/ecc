"""Compatibility alias for core invocation helpers."""

import sys

from chipcompiler.cli.core import invocation as _invocation

sys.modules[__name__] = _invocation
