from pathlib import Path
from typing import Any, TypedDict

from chipcompiler.utility import json_read

_REVIEW_GROUPS: tuple[tuple[str, str], ...] = (
    ("initial", "Initial"),
    ("config", "Config"),
    ("harden", "Harden"),
    ("final_design", "Final Design"),
    ("sta", "STA"),
    ("spef", "SPEF"),
    ("reports", "Reports"),
)


class _ReviewGroup(TypedDict):
    id: str
    label: str
    available: int
    expected: int
    blocked: list[dict]
    attention: list[dict]


def build_signoff_assessment(workspace: Any) -> dict[str, Any]:
    checklist = json_read(Path(workspace.directory) / "home" / "checklist.json")
    if checklist.get("schema_version") != 3 or checklist.get("kind") != "signoff_checklist":
        return _unavailable_assessment()

    groups: dict[str, _ReviewGroup] = {}
    for group_id, label in _REVIEW_GROUPS:
        groups[group_id] = {
            "id": group_id,
            "label": label,
            "available": 0,
            "expected": 0,
            "blocked": [],
            "attention": [],
        }
    for item in checklist.get("checklist", []):
        if not isinstance(item, dict):
            continue
        group = groups[_group_for(item)]
        group["expected"] += 1
        if item.get("state") == "pass":
            group["available"] += 1
        elif item.get("blocked") is True:
            group["blocked"].append(_detail(item))
        else:
            group["attention"].append(_detail(item))

    review_groups = []
    risks = []
    for group_id, _label in _REVIEW_GROUPS:
        group = groups[group_id]
        blocked = group["blocked"]
        attention = group["attention"]
        if blocked:
            status = "blocked"
            summary = f"{len(blocked)} blocking checklist requirements"
            risks.append(_risk(group, "blocked", blocked, summary))
            if attention:
                risks.append(
                    _risk(
                        group,
                        "warning",
                        attention,
                        f"{len(attention)} attention-only checklist requirements",
                    )
                )
        elif attention:
            status = "attention"
            summary = f"{len(attention)} attention-only checklist requirements"
            risks.append(_risk(group, "warning", attention, summary))
        else:
            status = "ready"
            summary = (
                f"{group['available']} of {group['expected']} requirements ready"
                if group["expected"]
                else "No requirements"
            )
        review_groups.append(
            {
                "id": group_id,
                "label": group["label"],
                "status": status,
                "available": group["available"],
                "expected": group["expected"],
                "summary": summary,
            }
        )

    status = checklist.get("status")
    return {
        "status": status if status in {"ready", "attention", "blocked"} else "blocked",
        "groups": review_groups,
        "risks": sorted(risks, key=lambda risk: risk["severity"] != "blocked"),
    }


def _risk(group: _ReviewGroup, severity: str, details: list[dict], summary: str) -> dict:
    result = "requirements block export" if severity == "blocked" else "attention"
    return {
        "severity": severity,
        "title": f"{group['label']} signoff {result}",
        "summary": summary,
        "details": details,
    }


def _detail(item: dict) -> dict:
    source = item.get("source", {})
    source = source if isinstance(source, dict) else {}
    evidence = item.get("evidence", [])
    return {
        "kind": item.get("category", "checklist"),
        "label": item.get("title", "Checklist item"),
        "location": source.get("path", "home/checklist.json"),
        "reason": item.get("summary", ""),
        "owner": item.get("owner", "checklist"),
        "policy": item.get("policy", "warn"),
        "state": item.get("state", "unavailable"),
        "evidence": evidence if isinstance(evidence, list) else [],
    }


def _group_for(item: dict) -> str:
    step = str(item.get("step", ""))
    category = str(item.get("category", ""))
    source = item.get("source", {})
    path = source.get("path", "") if isinstance(source, dict) else ""
    if category == "configuration" or path.startswith("config/"):
        return "config"
    if category == "provenance" or path.startswith(("origin/", "initial/")):
        return "initial"
    if step == "Harden" or path.startswith(("Harden_ecc/", "harden/")):
        return "harden"
    if step == "sta" or path.startswith(("sta_ecc/", "final/timing/sta/")):
        return "sta"
    if step == "RCX" or path.startswith(("RCX_ecc/", "final/timing/spef/")):
        return "spef"
    if step in {"Route", "drc", "lvs", "filler"} or path.startswith(
        ("route_ecc/", "drc_ecc/", "lvs_ecc/", "filler_ecc/", "final/design/")
    ):
        return "final_design"
    return "reports"


def _unavailable_assessment() -> dict[str, Any]:
    return {
        "status": "blocked",
        "groups": [
            {
                "id": group_id,
                "label": label,
                "status": "blocked" if group_id == "reports" else "ready",
                "available": 0,
                "expected": 0,
                "summary": (
                    "Checklist unavailable" if group_id == "reports" else "No requirements"
                ),
            }
            for group_id, label in _REVIEW_GROUPS
        ],
        "risks": [
            {
                "severity": "blocked",
                "title": "Signoff checklist unavailable",
                "summary": "Re-run signoff inspection after current-output analysis completes.",
                "details": [],
            }
        ],
    }
