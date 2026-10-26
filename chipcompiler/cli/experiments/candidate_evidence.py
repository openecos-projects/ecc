from chipcompiler.cli.inspection.evidence_summary import (
    checklist_items,
    checklist_status,
    flow_status,
    item_blocked,
    qor_score,
    step_status,
)


def _step_checklist(step: dict, checklist: dict) -> str:
    projection = step.get("checklist_status")
    if isinstance(projection, dict):
        if projection.get("blocked") is True:
            return "blocked"
        return checklist_status(projection)
    items = step.get("checklist")
    if isinstance(items, dict):
        return checklist_status(items)
    if not isinstance(items, list):
        items = [
            item for item in checklist_items(checklist) if item.get("step") == step.get("name")
        ]
    return checklist_status({"checklist": items})


def _signoff_status(payload: dict | list | str | int | float | None) -> str:
    if isinstance(payload, dict):
        return str(payload.get("status", "unknown"))
    if isinstance(payload, list):
        for record in payload:
            if isinstance(record, dict) and record.get("signoff") == "check":
                return str(record.get("status", "unknown"))
    return "unknown"


def _violation_count(payload: dict | list | str | int | float | None) -> int | str:
    if not isinstance(payload, list):
        return "unknown"
    required = {"drc_clean", "lvs_clean", "sta_setup_clean", "sta_hold_clean"}
    counts = {}
    for record in payload:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("gate"), str)
            or record["gate"] not in required
        ):
            continue
        count = record.get("violation_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            counts[record["gate"]] = count
    return sum(counts.values()) if set(counts) == required else "unknown"


def _advisory_only(checklist: dict, signoff_payload: object, signoff_status: str) -> bool:
    if checklist_status(checklist) != "attention" or signoff_status != "unknown":
        return False
    items = checklist_items(checklist)
    attention = [
        item for item in items if item.get("state", item.get("status")) not in {"pass", "passed"}
    ]
    if not attention or any(
        item.get("policy") != "warn" or item.get("blocked") is True for item in attention
    ):
        return False
    if not isinstance(signoff_payload, list):
        return False
    gates = {
        record.get("gate"): record
        for record in signoff_payload
        if isinstance(record, dict) and isinstance(record.get("gate"), str)
    }
    checklist_gate = gates.get("checklist_ready")
    if (
        not isinstance(checklist_gate, dict)
        or checklist_gate.get("status") != "unknown"
        or checklist_gate.get("reason") != "checklist_attention"
        or checklist_gate.get("failed_items")
        or checklist_gate.get("stale") is True
        or checklist_gate.get("provisional") is True
    ):
        return False
    return all(
        record.get("status") == "pass"
        for name, record in gates.items()
        if name != "checklist_ready" and record.get("required") is True
    )


def candidate_evidence(
    flow: dict,
    checklist: dict,
    qor: dict,
    *,
    exit_code: int,
    status_code: int,
    signoff_code: int,
    signoff_payload: dict | list | str | int | float | None,
) -> dict:
    raw_steps = flow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    step_statuses = [
        {
            "name": step.get("name", "unknown"),
            "status": step_status(step),
            "checklist": _step_checklist(step, checklist),
        }
        for step in steps
        if isinstance(step, dict)
    ]
    state = flow_status(flow)
    score = qor_score(qor)
    checks = checklist_status(checklist)
    signoff_status = _signoff_status(signoff_payload)
    advisory_only = signoff_code == 7 and _advisory_only(checklist, signoff_payload, signoff_status)
    blocked = (
        state == "blocked"
        or checks == "blocked"
        or any(item_blocked(item) for item in checklist_items(checklist))
        or any(step["checklist"] == "blocked" for step in step_statuses)
    )
    if exit_code != 0 or status_code != 0 or state == "failed":
        status = "failed"
    elif blocked:
        status = "blocked"
    elif signoff_code not in {0, 7}:
        status = "failed"
    elif (
        (signoff_code == 7 and not advisory_only)
        or (signoff_status != "pass" and not advisory_only)
        or state not in {"success", "passed"}
        or (checks != "passed" and not (advisory_only and checks == "attention"))
        or score is None
        or not step_statuses
        or any(step["status"] not in {"success", "passed"} for step in step_statuses)
    ):
        status = "unknown"
    else:
        status = "passed"
    return {
        "status": status,
        "signoff_status": signoff_status,
        "advisory_only": advisory_only,
        "step_statuses": step_statuses,
        "qor_score": score,
        "violation_count": _violation_count(signoff_payload),
        "signoff_exit_code": signoff_code,
        "workspace_status_exit_code": status_code,
    }
