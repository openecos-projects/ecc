"""Runtime signoff helpers (catalog, readiness, QoR metric reads)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "SIGNOFF_ITEM_CATALOG",
    "attach_readiness",
    "classify_signoff_readiness",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "SIGNOFF_ITEM_CATALOG": (".catalog", "SIGNOFF_ITEM_CATALOG"),
    "attach_readiness": (".readiness", "attach_readiness"),
    "classify_signoff_readiness": (".readiness", "classify_signoff_readiness"),
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
