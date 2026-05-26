"""Compatibility alias for configuration inspection helpers."""

import sys

from chipcompiler.cli.inspection import config_view as _config_view

sys.modules[__name__] = _config_view
