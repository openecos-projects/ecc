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
        "sta_setup_clean": _sta_gate(root, "setup"),
        "sta_hold_clean": _sta_gate(root, "hold"),
        "lec_proven": _lec_gate(root),
        "final_gds_available": _artifact_gate(root, "Harden GDS", "Harden_ecc/checklist.json"),
        "final_netlist_available": _netlist_artifact_gate(root),
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


def _sta_gate(root: Path, analysis: str) -> dict:
    result = _checker_gate(root, "sta")
    if result["status"] == "unknown":
        return result
    data = _read(root / "sta_ecc" / "checklist.json")
    items = data.get("checklist", []) if isinstance(data, dict) else []
    matching = [
        item
        for item in items
        if isinstance(item, dict)
        and analysis in f"{item.get('id', '')} {item.get('title', '')}".lower()
    ]
    source = "sta_ecc/checklist.json"
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
    result_path = root / "postRouteLec_kepler_formal" / "output"
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
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    relative = source.get("path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        return {"status": "unknown", "reason": "artifact_path_invalid", "source": checklist}
    artifact = (root / relative).resolve()
    if (
        root.resolve() not in artifact.parents
        or not artifact.is_file()
        or artifact.stat().st_size == 0
    ):
        return {"status": "unknown", "reason": "artifact_unavailable", "source": relative}
    if item.get("state") != "pass" or item.get("blocked") is True:
        return {"status": "fail", "reason": "artifact_checklist_failed", "source": relative}
    return {"status": "pass", "reason": "artifact_available", "source": relative}


def _netlist_artifact_gate(root: Path) -> dict:
    result_path = root / "postRouteLec_kepler_formal" / "output"
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
    artifact = Path(relative)
    if artifact.is_absolute():
        try:
            artifact = artifact.resolve().relative_to(root.resolve())
        except ValueError:
            return {
                "status": "unknown",
                "reason": "artifact_outside_workspace",
                "source": str(candidates[0].relative_to(root)),
            }
    target = (root / artifact).resolve()
    if root.resolve() not in target.parents or not target.is_file() or target.stat().st_size == 0:
        return {"status": "unknown", "reason": "artifact_unavailable", "source": str(artifact)}
    return {
        "status": "pass",
        "reason": "artifact_available",
        "source": str(target.relative_to(root)),
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
