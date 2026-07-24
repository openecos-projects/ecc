from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from chipcompiler.engine import EngineFlow, SignoffPackageOptions
from chipcompiler.runtime.workspace_api import RuntimeApiError
from chipcompiler.utility import json_read

_REVIEW_GROUPS = (
    ("initial", "Initial"),
    ("config", "Config"),
    ("harden", "Harden"),
    ("final_design", "Final Design"),
    ("sta", "STA"),
    ("spef", "SPEF"),
    ("reports", "Reports"),
)


def inspect_signoff_package(workspace) -> dict:
    """Refresh current outputs, then render the home checklist contract only."""
    EngineFlow(workspace).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False, refresh_analysis=True)
    )
    checklist_path = Path(workspace.directory) / "home" / "checklist.json"
    checklist_data = json_read(checklist_path)
    if (
        checklist_data.get("schema_version") != 3
        or checklist_data.get("kind") != "signoff_checklist"
    ):
        return _unavailable_review()

    groups = {
        group_id: {
            "id": group_id,
            "label": label,
            "available": 0,
            "expected": 0,
            "blocked_details": [],
            "attention_details": [],
        }
        for group_id, label in _REVIEW_GROUPS
    }
    for item in checklist_data.get("checklist", []):
        if not isinstance(item, dict):
            continue
        group = groups[_review_group_for_item(item)]
        group["expected"] += 1
        if item.get("state") == "pass":
            group["available"] += 1
        elif item.get("blocked") is True:
            group["blocked_details"].append(_review_detail(item))
        else:
            group["attention_details"].append(_review_detail(item))

    review_groups = []
    risks = []
    for group_id, _label in _REVIEW_GROUPS:
        group = groups[group_id]
        blocked_details = group["blocked_details"]
        attention_details = group["attention_details"]
        available = group["available"]
        expected = group["expected"]
        if blocked_details:
            status = "blocked"
            summary = f"{len(blocked_details)} blocking checklist requirements"
            risks.append(
                {
                    "severity": "blocked",
                    "title": f"{group['label']} signoff requirements block export",
                    "summary": summary,
                    "details": blocked_details,
                }
            )
            if attention_details:
                risks.append(
                    {
                        "severity": "warning",
                        "title": f"{group['label']} signoff attention",
                        "summary": (
                            f"{len(attention_details)} attention-only checklist requirements"
                        ),
                        "details": attention_details,
                    }
                )
        elif attention_details:
            status = "attention"
            summary = f"{len(attention_details)} attention-only checklist requirements"
            risks.append(
                {
                    "severity": "warning",
                    "title": f"{group['label']} signoff attention",
                    "summary": summary,
                    "details": attention_details,
                }
            )
        else:
            status = "ready"
            summary = (
                f"{available} of {expected} requirements ready" if expected else "No requirements"
            )
        review_groups.append(
            {
                "id": group_id,
                "label": group["label"],
                "status": status,
                "available": available,
                "expected": expected,
                "summary": summary,
            }
        )

    risks.sort(key=lambda risk: risk["severity"] != "blocked")
    status = checklist_data.get("status")
    return {
        "status": status if status in {"ready", "attention", "blocked"} else "blocked",
        "groups": review_groups,
        "risks": risks,
    }


def _unavailable_review() -> dict:
    detail = {
        "kind": "freshness",
        "label": "Signoff checklist",
        "location": "home/checklist.json",
        "reason": "The current signoff checklist could not be generated.",
        "owner": "checklist",
        "policy": "block",
        "state": "unavailable",
        "evidence": [],
    }
    return {
        "status": "blocked",
        "groups": [
            {
                "id": group_id,
                "label": label,
                "status": "blocked" if group_id == "reports" else "ready",
                "available": 0,
                "expected": 0,
                "summary": "Checklist unavailable" if group_id == "reports" else "No requirements",
            }
            for group_id, label in _REVIEW_GROUPS
        ],
        "risks": [
            {
                "severity": "blocked",
                "title": "Signoff checklist unavailable",
                "summary": "Re-run signoff inspection after current-output analysis completes.",
                "details": [detail],
            }
        ],
    }


def _review_detail(item: dict) -> dict:
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


def _review_group_for_item(item: dict) -> str:
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
    if step in {"Route", "drc", "filler"} or path.startswith(
        ("route_ecc/", "drc_ecc/", "filler_ecc/", "final/design/")
    ):
        return "final_design"
    return "reports"


def export_signoff_package_archive(workspace, output_path: str) -> str:
    raw_destination = Path(output_path).expanduser()
    destination = raw_destination.parent.resolve() / raw_destination.name

    with tempfile.TemporaryDirectory(prefix="ecc-signoff-") as temporary_root:
        result = EngineFlow(workspace).collect_signoff_package(
            SignoffPackageOptions(
                output_dir=temporary_root,
                archive=True,
                refresh_analysis=True,
            )
        )
        if not result.ok:
            missing = ", ".join(result.missing_required) or "unknown required resources"
            raise RuntimeApiError(
                "command_failed",
                f"signoff package is incomplete: {missing}",
            )
        if not result.archive_path:
            raise RuntimeApiError(
                "command_failed",
                "signoff package archive was not created",
            )

        archive = Path(result.archive_path)
        if not archive.is_file():
            raise RuntimeApiError(
                "command_failed",
                "signoff package archive does not exist",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staged_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
        )
        os.close(descriptor)
        staged_path = Path(staged_name)
        try:
            shutil.copy2(archive, staged_path)
            os.replace(staged_path, destination)
        finally:
            staged_path.unlink(missing_ok=True)

    return str(destination)
