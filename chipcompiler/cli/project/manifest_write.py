"""CLI compatibility alias for Project Manifest mutations."""

import sys

from chipcompiler.project import manifest_write as _domain_manifest_write

sys.modules[__name__] = _domain_manifest_write
