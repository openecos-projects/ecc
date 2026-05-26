"""Compatibility alias for workspace service helpers."""

import sys

from chipcompiler.cli.workspace import service as _service

sys.modules[__name__] = _service
