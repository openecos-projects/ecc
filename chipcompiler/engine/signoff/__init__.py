"""Signoff package collection and design-summary reporting.

Catalog / readiness live under ``chipcompiler.runtime.signoff``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SIGNOFF_REQUIRED_QOR_STEPS",
    "SignoffPackageCollector",
    "SignoffPackageIssue",
    "SignoffPackageOptions",
    "SignoffPackageResult",
    "generate_text_report",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "SIGNOFF_REQUIRED_QOR_STEPS": (".models", "SIGNOFF_REQUIRED_QOR_STEPS"),
    "SignoffPackageCollector": (".collector", "SignoffPackageCollector"),
    "SignoffPackageIssue": (".models", "SignoffPackageIssue"),
    "SignoffPackageOptions": (".models", "SignoffPackageOptions"),
    "SignoffPackageResult": (".models", "SignoffPackageResult"),
    "generate_text_report": (".report", "generate_text_report"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
