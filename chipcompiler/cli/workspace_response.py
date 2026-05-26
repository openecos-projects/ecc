"""Compatibility alias for workspace response helpers."""

import sys

from chipcompiler.cli.workspace import response as _response

sys.modules[__name__] = _response
