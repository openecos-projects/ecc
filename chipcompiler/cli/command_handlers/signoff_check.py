import json
from pathlib import Path

from chipcompiler.cli.core.exit_codes import EXIT_GATE_FAILED, EXIT_GATE_UNKNOWN
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.artifact_evidence import inspect_artifact
from chipcompiler.cli.inspection.discovery import (
    resolve_loaded_workspace,
    workspace_display,
)
from chipcompiler.cli.inspection.evidence_summary import qor_score
from chipcompiler.cli.inspection.project_checkers import checker_evidence
from chipcompiler.data import SkippableStepEnum, StepEnum
from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.utility import JsonObject

_PROFILES = {
    "rtl2gds": (
        "flow_complete",
        "qor_available",
        "checklist_ready",
        "drc_clean",
        "lvs_clean",
        "sta_setup_clean",
        "sta_hold_clean",
    ),
    "physical_signoff": (
        "flow_complete",
        "qor_available",
        "checklist_ready",
        "drc_clean",
        "lvs_clean",
        "sta_setup_clean",
        "sta_hold_clean",
        "lec_proven",
        "final_gds_available",
        "final_netlist_available",
    ),
}

_REQUIRED_GATES = {
    "rtl2gds": _PROFILES["rtl2gds"],
    "physical_signoff": (
        "flow_complete",
        "drc_clean",
        "lvs_clean",
        "sta_setup_clean",
        "sta_hold_clean",
        "lec_proven",
        "final_gds_available",
        "final_netlist_available",
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
        "drc_clean": _metric_checker_gate(root, "drc"),
        "lvs_clean": _metric_checker_gate(root, "lvs"),
        "sta_setup_clean": _metric_checker_gate(root, "sta", "sta_setup_violation_count"),
        "sta_hold_clean": _metric_checker_gate(root, "sta", "sta_hold_violation_count"),
        "lec_proven": _lec_gate(root),
        "final_gds_available": _artifact_gate(
            root, "Harden GDS", f"{STEP_DIRECTORIES[StepEnum.HARDEN.value]}/checklist.json"
        ),
        "final_netlist_available": _netlist_artifact_gate(root),
    }
    status = _overall(gates, _REQUIRED_GATES[command_input.profile])
    records = [
        {
            "signoff": "check",
            "profile": command_input.profile,
            "workspace": workspace_display(command_input, ctx),
            "status": status,
        }
    ]
    records.extend(
        {
            "gate": name,
            "required": name in _REQUIRED_GATES[command_input.profile],
            **_contract_gate(gate),
        }
        for name in _PROFILES[command_input.profile]
        for gate in [gates[name]]
    )
    exit_code = {
        "pass": 0,
        "fail": EXIT_GATE_FAILED,
        "unknown": EXIT_GATE_UNKNOWN,
    }[status]
    return CommandResult(records=tuple(records), exit_code=exit_code)


def _contract_gate(gate: dict) -> dict:
    """Return the stable gate contract shared by CLI and GUI consumers."""
    result = {
        "status": gate.get("status", "unknown"),
        "reason": gate.get("reason"),
        "source": gate.get("source"),
        "failed_items": gate.get("failed_items", []),
        "violation_count": gate.get("violation_count"),
        "stale": bool(gate.get("stale", False)),
        "provisional": bool(gate.get("provisional", False)),
    }
    for key in ("bytes", "sha256"):
        if key in gate:
            result[key] = gate[key]
    return result


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
    score = qor_score(data) if isinstance(data, dict) else None
    if score is not None:
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
    step_directory = STEP_DIRECTORIES[checker]
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


def _metric_checker_gate(root: Path, checker: str, metric_id: str | None = None) -> dict:
    """Build a signoff gate from the canonical checker metric evidence."""
    flow = _read(root / "home" / "flow.json")
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    step = next(
        (
            item
            for item in steps
            if isinstance(item, dict) and str(item.get("name", "")).lower() == checker
        ),
        {"name": checker, "tool": "ecc", "state": "Success"},
    )
    evidence = checker_evidence(root, step, str(flow.get("design", "design")))
    counts = evidence.get("counts", {})
    selected = counts.get(metric_id) if metric_id else evidence.get("violation_count")
    source = evidence.get("source")
    base = {
        "source": source,
        "violation_count": selected,
        "failed_items": [],
        "stale": evidence.get("availability") in {"missing", "corrupt", "invalid"},
        "provisional": evidence.get("availability") != "available",
    }
    if evidence.get("availability") in {"available", "partial"} and selected is not None:
        base.update(
            status="pass" if selected == 0 else "fail",
            reason=f"{checker}_clean" if selected == 0 else f"{checker}_violations",
        )
        if selected:
            base["failed_items"] = [f"{metric_id or checker}={selected}"]
        return base
    base.update(status="unknown", reason=f"{checker}_evidence_unavailable")
    return base


def _sta_gate(root: Path, analysis: str) -> dict:
    result = _checker_gate(root, "sta")
    if result["status"] == "unknown":
        return result
    data = _read(root / STEP_DIRECTORIES[StepEnum.STA.value] / "checklist.json")
    items = data.get("checklist", []) if isinstance(data, dict) else []
    matching = [
        item
        for item in items
        if isinstance(item, dict)
        and analysis in f"{item.get('id', '')} {item.get('title', '')}".lower()
    ]
    source = f"{STEP_DIRECTORIES[StepEnum.STA.value]}/checklist.json"
    if not matching:
        return {
            "status": "unknown",
            "reason": f"sta_{analysis}_evidence_unavailable",
            "source": source,
            "failed_items": [],
        }
    failed_items = [item.get("title", "") for item in matching if item.get("state") != "pass"]
    return {
        "status": "fail" if failed_items else "pass",
        "reason": f"sta_{analysis}_{'violations' if failed_items else 'clean'}",
        "source": source,
        "failed_items": failed_items,
        "violation_count": None,
    }


def _lec_gate(root: Path) -> dict:
    result_path = root / STEP_DIRECTORIES[SkippableStepEnum.POST_ROUTE_LEC.value] / "output"
    candidates = list(result_path.glob("*_result.json")) if result_path.is_dir() else []
    if len(candidates) != 1:
        return {
            "status": "unknown",
            "reason": "lec_evidence_unavailable",
            "source": str(result_path.relative_to(root)),
        }
    data = _read(candidates[0])
    if data.get("status") == "proven":
        return {
            "status": "pass",
            "reason": "lec_proven",
            "source": str(candidates[0].relative_to(root)),
        }
    if data:
        return {
            "status": "fail",
            "reason": "lec_not_proven",
            "source": str(candidates[0].relative_to(root)),
        }
    return {
        "status": "unknown",
        "reason": "lec_evidence_invalid",
        "source": str(candidates[0].relative_to(root)),
    }


def _artifact_gate(root: Path, label: str, checklist: str) -> dict:
    checklist_path = root / checklist
    data = _read(checklist_path)
    items = data.get("checklist", []) if isinstance(data, dict) else []
    item = next((item for item in items if item.get("title") == label), None)
    if not isinstance(item, dict):
        return {"status": "unknown", "reason": "artifact_evidence_unavailable", "source": checklist}
    source = JsonObject(item.get("source"))
    relative = source.get("path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        return {"status": "unknown", "reason": "artifact_path_invalid", "source": checklist}
    evidence = inspect_artifact(root, relative, include_hash=True)
    if evidence["availability"] != "available" or evidence["bytes"] == 0:
        return {"status": "unknown", "reason": "artifact_unavailable", "source": relative}
    if item.get("state") != "pass" or item.get("blocked") is True:
        return {"status": "fail", "reason": "artifact_checklist_failed", "source": relative}
    return {
        "status": "pass",
        "reason": "artifact_available",
        "source": relative,
        "bytes": evidence["bytes"],
        "sha256": evidence["sha256"],
    }


def _netlist_artifact_gate(root: Path) -> dict:
    result_path = root / STEP_DIRECTORIES[SkippableStepEnum.POST_ROUTE_LEC.value] / "output"
    candidates = list(result_path.glob("*_result.json")) if result_path.is_dir() else []
    if len(candidates) != 1:
        return {
            "status": "unknown",
            "reason": "artifact_evidence_unavailable",
            "source": "postRouteLec_kepler_formal/output",
        }
    result = _read(candidates[0])
    relative = result.get("gate_verilog")
    if not isinstance(relative, str):
        return {
            "status": "unknown",
            "reason": "artifact_path_invalid",
            "source": str(candidates[0].relative_to(root)),
        }
    evidence = inspect_artifact(root, relative, include_hash=True)
    if evidence["availability"] != "available" or evidence["bytes"] == 0:
        reason = (
            "artifact_outside_workspace"
            if evidence["availability"] == "outside_workspace"
            else "artifact_unavailable"
        )
        return {"status": "unknown", "reason": reason, "source": str(relative)}
    return {
        "status": "pass",
        "reason": "artifact_available",
        "source": evidence["path"],
        "bytes": evidence["bytes"],
        "sha256": evidence["sha256"],
    }


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _overall(gates: dict[str, dict], required: tuple[str, ...] | None = None) -> str:
    selected = [gates[name] for name in required] if required is not None else list(gates.values())
    statuses = {gate["status"] for gate in selected}
    if "fail" in statuses:
        return "fail"
    if statuses == {"pass"}:
        return "pass"
    return "unknown"
