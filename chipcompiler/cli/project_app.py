"""Compatibility alias for project command registration."""

import sys

from chipcompiler.cli.commands import project as _project

sys.modules[__name__] = _project
