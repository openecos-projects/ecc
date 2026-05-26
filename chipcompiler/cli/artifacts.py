"""Compatibility alias for artifact inspection helpers."""

import sys

from chipcompiler.cli.inspection import artifacts as _artifacts

sys.modules[__name__] = _artifacts
