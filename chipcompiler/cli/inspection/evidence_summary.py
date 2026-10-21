import json
import math
from pathlib import Path

from chipcompiler.cli.core.output import normalize_state
from chipcompiler.cli.inspection.discovery import get_run_status


def read_flow_file(path: str | Path) -> tuple[dict, str | None]:
    """Read and minimally validate a persisted flow ledger.

    All read-only CLI projections use this boundary so malformed or missing
    ledgers cannot be silently treated as an empty successful flow.
    """
    flow_path = Path(path)
    try:
        value = json.loads(flow_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, str(exc)
    if not isinstance(value, dict):
        return {}, "flow.json must contain a steps list"
    if not isinstance(value.get("steps"), list) and not isinstance(
        value.get("status", value.get("state")), str
    ):
        return {}, "flow.json must contain a steps list"
    return value, None


def flow_status(flow: dict) -> str:
    steps = flow.get("steps")
    if isinstance(steps, list) and steps:
        states = [step_status(step) for step in steps if isinstance(step, dict)]
        if len(states) != len(steps) or "unknown" in states:
            return "unknown"
        if "blocked" in states:
            return "blocked"
        return get_run_status(
            {
                "steps": [
                    {"name": step.get("name"), "state": "success" if state == "passed" else state}
                    for step, state in zip(steps, states, strict=True)
                ]
            }
        )
    status = flow.get("status", flow.get("state", "unknown"))
    return normalize_state(status) if isinstance(status, str) else "unknown"


def step_status(step: dict) -> str:
    status = step.get("state", step.get("status", "unknown"))
    return normalize_state(status) if isinstance(status, str) else "unknown"


def checklist_items(checklist: dict) -> list[dict]:
    items = checklist.get("checklist", checklist.get("items", []))
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def item_blocked(item: dict) -> bool:
    state = item.get("state", item.get("status"))
    return bool(
        item.get(
            "blocked",
            state == "blocked"
            or (
                item.get("policy", "block") == "block"
                and state in ("failed", "fail", "unavailable")
            ),
        )
    )


def checklist_status(checklist: dict) -> str:
    items = checklist_items(checklist)
    if any(item_blocked(item) for item in items) or checklist.get("status") == "blocked":
        return "blocked"
    states = [item.get("state", item.get("status")) for item in items]
    if "warning" in states or checklist.get("status") == "attention":
        return "attention"
    if states and all(state in ("pass", "passed") for state in states):
        return "passed"
    return "passed" if checklist.get("status") in ("ready", "passed") else "unknown"


def qor_score(report: dict) -> float | None:
    summary = report.get("scalar_summary")
    if isinstance(summary, dict):
        if summary.get("status") == "NOT_RATED":
            return None
        score = summary.get("score")
    else:
        score = report.get("qor_score", report.get("score"))
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        try:
            value = float(score)
        except OverflowError:
            return None
        if math.isfinite(value):
            return value
    return None
