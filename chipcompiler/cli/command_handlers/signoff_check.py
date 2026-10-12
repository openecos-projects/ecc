import json
from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import (
    resolve_loaded_workspace,
    workspace_display,
)

_PROFILES = {
    "rtl2gds": (
        "flow_complete",
        "qor_available",
        "checklist_ready",
        "drc_clean",
        "lvs_clean",
        "sta_clean",
    ),
}


def check(command_input, ctx: CommandContext) -> CommandResult:
    if command_input.profile not in _PROFILES:
        return CommandResult.err(
            [error_record("unknown_signoff_profile", profile=command_input.profile)]
        )
    workspace, failure = resolve_loaded_workspace(command_input, ctx)
    if failure is not None:
        return failure
    root = Path(workspace.directory or "")
    from chipcompiler.engine.signoff_export import inspect_signoff_package

    review = inspect_signoff_package(workspace)
    gates = {
        "flow_complete": _flow_gate(root),
        "qor_available": _qor_gate(root),
        "checklist_ready": _checklist_gate(review),
        "drc_clean": _checker_gate(root, "drc"),
        "lvs_clean": _checker_gate(root, "lvs"),
        "sta_clean": _checker_gate(root, "sta"),
    }
    records = [
        {
            "signoff": "check",
            "profile": command_input.profile,
            "workspace": workspace_display(command_input, ctx),
            "status": _overall(gates),
        }
    ]
    records.extend(
        {"gate": name, **gate}
        for name in _PROFILES[command_input.profile]
        for gate in [gates[name]]
    )
    return CommandResult.ok(records)


def _flow_gate(root: Path) -> dict:
    data = _read(root / "home" / "flow.json")
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        return {"status": "unknown", "reason": "flow_unavailable", "source": "home/flow.json"}
    states = [step.get("state") for step in steps if isinstance(step, dict)]
    if not states or any(state in {"Failed", "Unstart", "Ongoing"} for state in states):
        return {"status": "fail", "reason": "flow_not_complete", "source": "home/flow.json"}
    return {
        "status": "pass" if all(state == "Success" for state in states) else "unknown",
        "reason": "flow_state",
        "source": "home/flow.json",
    }


def _qor_gate(root: Path) -> dict:
    data = _read(root / "home" / "qor_report.json")
    score = data.get("score") if isinstance(data, dict) else None
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return {"status": "pass", "reason": "qor_available", "source": "home/qor_report.json"}
    return {"status": "unknown", "reason": "qor_unavailable", "source": "home/qor_report.json"}


def _checklist_gate(review: dict) -> dict:
    status = review.get("status")
    if status == "ready":
        return {"status": "pass", "reason": "checklist_ready", "source": "home/checklist.json"}
    if status == "blocked":
        return {"status": "fail", "reason": "checklist_blocked", "source": "home/checklist.json"}
    return {"status": "unknown", "reason": "checklist_attention", "source": "home/checklist.json"}


def _checker_gate(root: Path, checker: str) -> dict:
    step_directory = {"drc": "drc_ecc", "lvs": "lvs_ecc", "sta": "sta_ecc"}[checker]
    source_path = root / step_directory / "checklist.json"
    data = _read(source_path)
    if not data:
        source_path = root / "home" / "checklist.json"
        data = _read(source_path)
    items = data.get("checklist", []) if isinstance(data, dict) else []
    matching = [
        item
        for item in items
        if isinstance(item, dict)
        and (
            str(item.get("category", "")).lower() == checker
            or str(item.get("step", "")).lower() == checker
            or (
                source_path.parent.name == step_directory
                and item.get("category") in {"quality_gate", "artifact", "report"}
            )
        )
    ]
    if not matching:
        return {
            "status": "unknown",
            "reason": f"{checker}_evidence_unavailable",
            "source": str(source_path.relative_to(root)),
            "violation_count": None,
            "failed_items": [],
        }
    failed_items = [
        item.get("title", "")
        for item in matching
        if item.get("state") == "fail" or item.get("blocked") is True
    ]
    if any(item.get("state") == "fail" or item.get("blocked") is True for item in matching):
        return {
            "status": "fail",
            "reason": f"{checker}_violations",
            "source": str(source_path.relative_to(root)),
            "violation_count": None,
            "failed_items": failed_items,
        }
    quality_gates = [item for item in matching if item.get("category") == "quality_gate"]
    if quality_gates and all(item.get("state") == "pass" for item in quality_gates):
        return {
            "status": "pass",
            "reason": f"{checker}_clean",
            "source": str(source_path.relative_to(root)),
            "violation_count": None,
            "failed_items": [],
        }
    return {
        "status": "unknown",
        "reason": f"{checker}_incomplete",
        "source": str(source_path.relative_to(root)),
        "violation_count": None,
        "failed_items": failed_items,
    }


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _overall(gates: dict[str, dict]) -> str:
    statuses = {gate["status"] for gate in gates.values()}
    if "fail" in statuses:
        return "fail"
    if statuses == {"pass"}:
        return "pass"
    return "unknown"
