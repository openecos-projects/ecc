"""Compatibility alias for project configuration helpers."""

import sys

from chipcompiler.cli.project import config as _config

sys.modules[__name__] = _config
