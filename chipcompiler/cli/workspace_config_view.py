"""Compatibility alias for workspace config view helpers."""

import sys

from chipcompiler.cli.workspace import config_view as _config_view

sys.modules[__name__] = _config_view
