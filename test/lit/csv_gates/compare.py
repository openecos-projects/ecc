"""Gate evaluation for signoff CSV CI profiles.

Narrow CI contract math (metric op/reference, checklist require_*).
Run-vs-run / dashboard diffs stay outside ecc (e.g. csvkit or a consumer).
"""

from __future__ import annotations

METRIC_OPS = ("==", "!=", ">=", "<=", ">", "<")


def as_number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in {"true", "false", "nan", "inf", "+inf", "-inf"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def compare_values(op: str, actual, reference) -> bool:
    """Compare actual vs reference under ``op`` (numeric when both parse)."""
    left, right = as_number(actual), as_number(reference)
    if left is None or right is None:
        if op == "==":
            return str(actual) == str(reference)
        if op == "!=":
            return str(actual) != str(reference)
        return False
    return {
        "==": left == right,
        "!=": left != right,
        ">=": left >= right,
        "<=": left <= right,
        ">": left > right,
        "<": left < right,
    }.get(op, False)


def evaluate_metric_gate(row: dict, spec) -> str:
    """Return ``pass``/``fail`` for one metric row. ``spec`` needs ``reference`` + ``op``."""
    if str(row.get("present", "true")).lower() == "false":
        return "fail"
    if spec.reference is None:
        return "pass"
    return "pass" if compare_values(spec.op, row.get("value"), spec.reference) else "fail"


def evaluate_checklist_gate(row: dict, spec) -> str:
    """Return ``pass``/``fail`` for one checklist row. ``spec`` needs require_* fields."""
    if str(row.get("present", "true")).lower() == "false":
        return "fail"
    if spec.require_state is not None and str(row.get("state", "")).strip() != spec.require_state:
        return "fail"
    if spec.require_blocked is not None:
        blocked = parse_bool(row.get("blocked"))
        if blocked is None or blocked != spec.require_blocked:
            return "fail"
    return "pass"
