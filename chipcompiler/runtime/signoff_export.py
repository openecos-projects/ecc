from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from chipcompiler.engine import EngineFlow, SignoffPackageOptions
from chipcompiler.runtime.workspace_api import RuntimeApiError

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
    result = EngineFlow(workspace).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False, refresh_analysis=True)
    )
    groups = {
        group_id: {
            "id": group_id,
            "label": label,
            "available": 0,
            "missing_required": 0,
            "missing_optional": 0,
            "warning": False,
            "blocked_details": [],
            "warning_details": [],
            "analysis_blocked": [],
            "analysis_warning": [],
        }
        for group_id, label in _REVIEW_GROUPS
    }
    flow_details = []
    checklist_details = []

    for copied in result.copied:
        destination = copied.get("destination", "")
        groups[_review_group_id(destination)]["available"] += 1
    for missing in result.missing_required:
        if missing.startswith("flow step "):
            continue
        if missing.startswith("analysis/"):
            continue
        groups[_review_group_id(missing)]["missing_required"] += 1
    for missing in result.missing_optional:
        if missing.startswith("analysis/"):
            continue
        groups[_review_group_id(missing)]["missing_optional"] += 1
    for issue in getattr(result, "issues", []):
        detail = _review_detail(issue)
        if issue.kind == "flow":
            flow_details.append(detail)
        elif issue.kind == "checklist":
            checklist_details.append(detail)
        elif issue.kind in {"analysis", "freshness"}:
            detail_key = "analysis_blocked" if issue.required else "analysis_warning"
            groups[_review_group_id(issue.destination)][detail_key].append(detail)
        elif issue.kind == "resource":
            detail_key = "blocked_details" if issue.required else "warning_details"
            groups[_review_group_id(issue.destination)][detail_key].append(detail)
    if checklist_details:
        groups["reports"]["warning"] = True

    review_groups = []
    risks = []
    if flow_details:
        risks.append(
            {
                "severity": "blocked",
                "title": "Flow requirements not complete",
                "summary": _flow_summary(len(flow_details)),
                "details": flow_details,
            }
        )
    for group_id, _label in _REVIEW_GROUPS:
        group = groups[group_id]
        required_missing = group.pop("missing_required")
        optional_missing = group.pop("missing_optional")
        checklist_warning = group.pop("warning")
        blocked_details = group.pop("blocked_details")
        warning_details = group.pop("warning_details")
        analysis_blocked = group.pop("analysis_blocked")
        analysis_warning = group.pop("analysis_warning")
        available = group["available"]
        expected = available + required_missing + optional_missing

        if required_missing:
            status = "blocked"
            summary = _missing_summary(required_missing, "required")
            risks.append(
                {
                    "severity": "blocked",
                    "title": f"{group['label']} resources missing",
                    "summary": summary,
                    "details": blocked_details,
                }
            )
        elif analysis_blocked:
            status = "blocked"
            summary = "Current QoR analysis blocks signoff"
            risks.append(
                {
                    "severity": "blocked",
                    "title": f"{group['label']} QoR analysis blocks signoff",
                    "summary": summary,
                    "details": analysis_blocked,
                }
            )
        elif optional_missing or checklist_warning or analysis_warning:
            status = "attention"
            if optional_missing:
                summary = _missing_summary(optional_missing, "optional")
            elif checklist_warning:
                summary = "Checklist requires attention"
            else:
                summary = "QoR analysis requires attention"
            if optional_missing:
                risks.append(
                    {
                        "severity": "warning",
                        "title": f"{group['label']} optional resources missing",
                        "summary": summary,
                        "details": warning_details,
                    }
                )
            if analysis_warning:
                risks.append(
                    {
                        "severity": "warning",
                        "title": f"{group['label']} QoR analysis requires attention",
                        "summary": "One or more current QoR metrics are unavailable or incomplete",
                        "details": analysis_warning,
                    }
                )
        else:
            status = "ready"
            summary = (
                f"{available} of {expected} resources ready"
                if expected
                else "No resources expected"
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

    if checklist_details:
        risks.append(
            {
                "severity": "warning",
                "title": "Checklist attention",
                "summary": "The workspace checklist contains failed or warning items",
                "details": checklist_details,
            }
        )

    risks.sort(key=lambda risk: risk["severity"] != "blocked")

    return {
        "status": "blocked" if result.missing_required else "attention" if risks else "ready",
        "groups": review_groups,
        "risks": risks,
    }


def _review_detail(issue) -> dict:
    return {
        "kind": issue.kind,
        "label": issue.label,
        "location": issue.location,
        "reason": issue.reason,
    }


def _review_group_id(resource: str) -> str:
    if resource.startswith("analysis/Harden/"):
        return "harden"
    if resource.startswith("analysis/sta/"):
        return "sta"
    if resource.startswith("analysis/RCX/"):
        return "spef"
    if resource.startswith(("analysis/drc/", "analysis/filler/", "analysis/route/")):
        return "final_design"
    if resource.startswith("initial/") or resource.startswith("origin "):
        return "initial"
    if resource.startswith("config/") or resource == "config directory":
        return "config"
    if resource.startswith("harden/"):
        return "harden"
    if resource.startswith("final/design/"):
        return "final_design"
    if resource.startswith("final/timing/sta/"):
        return "sta"
    if resource.startswith("final/timing/spef/") or resource == "RCX SPEF files":
        return "spef"
    return "reports"


def _missing_summary(count: int, kind: str) -> str:
    suffix = "resource" if count == 1 else "resources"
    return f"{count} {kind} {suffix} missing"


def _flow_summary(count: int) -> str:
    suffix = "step is" if count == 1 else "steps are"
    return f"{count} required flow {suffix} not successful"


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
                f"signoff package archive does not exist: {archive}",
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
