"""Compatibility alias for workspace command registration."""

import sys

from chipcompiler.cli.commands import workspace as _workspace

sys.modules[__name__] = _workspace
