"""Compatibility alias for workspace request helpers."""

import sys

from chipcompiler.cli.workspace import request as _request

sys.modules[__name__] = _request
