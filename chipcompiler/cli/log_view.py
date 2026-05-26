"""Compatibility alias for log inspection helpers."""

import sys

from chipcompiler.cli.inspection import log_view as _log_view

sys.modules[__name__] = _log_view
