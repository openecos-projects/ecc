"""CLI compatibility alias for the Project Manifest domain module."""

import sys

from chipcompiler.project import manifest as _domain_manifest

sys.modules[__name__] = _domain_manifest
