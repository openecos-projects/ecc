"""Signoff package collection and design-summary reporting.

Public surface: :class:`SignoffPackageCollector` and its option/result
model (see collector.py and models.py), plus the GUI-parity text design
summary implemented in engine.signoff.report*.
"""

from chipcompiler.engine.signoff.collector import SignoffPackageCollector
from chipcompiler.engine.signoff.models import (
    SIGNOFF_REQUIRED_QOR_STEPS,
    SignoffPackageIssue,
    SignoffPackageOptions,
    SignoffPackageResult,
)

__all__ = [
    "SIGNOFF_REQUIRED_QOR_STEPS",
    "SignoffPackageCollector",
    "SignoffPackageIssue",
    "SignoffPackageOptions",
    "SignoffPackageResult",
]


# the engine.signoff.report* sibling modules, re-exported here as the API.
from chipcompiler.engine.signoff.report import generate_text_report  # noqa: E402,F401
