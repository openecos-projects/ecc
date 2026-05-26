"""Compatibility alias for project parameter helpers."""

import sys

from chipcompiler.cli.project import params as _params

sys.modules[__name__] = _params
