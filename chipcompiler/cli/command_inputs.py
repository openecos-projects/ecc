"""Compatibility alias for core command input records."""

import sys

from chipcompiler.cli.core import inputs as _inputs

sys.modules[__name__] = _inputs
