from pathlib import Path

from chipcompiler.analysis.qor.schema import validate_report
from chipcompiler.cli.core.output import normalize_state, normalize_step_name
from chipcompiler.cli.inspection.discovery import get_run_status
from chipcompiler.cli.inspection.project_artifacts import read_workspace_artifact
from chipcompiler.cli.inspection.project_checkers import checker_evidence
from chipcompiler.data.types import FlowStepCategory
from chipcompiler.data.workspace.flow_policy import flow_category
from chipcompiler.engine.snapshot_limits import ENGINEERING_SNAPSHOT_MAX_BYTES
from chipcompiler.project.manifest import ProjectManifest


def _flow(root: Path) -> tuple[list[dict], str]:
    result = read_workspace_artifact(
        root, root / "home" / "flow.json", ENGINEERING_SNAPSHOT_MAX_BYTES
    )
    if result.status != "available" or result.data is None:
        return [], result.status
    steps = result.data.get("steps")
    if not isinstance(steps, list) or any(
        not isinstance(step, dict)
        or not isinstance(step.get("name"), str)
        or not step["name"]
        or not isinstance(step.get("tool"), str)
        or not step["tool"]
        or not isinstance(step.get("state"), str)
        for step in steps
    ):
        return [], "invalid"
    identities = [(step["name"], step["tool"]) for step in steps]
    if len(identities) != len(set(identities)):
        return [], "invalid"
    return steps, get_run_status(result.data)


def _qor(root: Path, steps: list[dict], flow_status: str) -> dict:
    source = root / "home" / "qor_report.json"
    result = read_workspace_artifact(root, source, ENGINEERING_SNAPSHOT_MAX_BYTES)
    record = {
        "score": None,
        "availability": result.status,
        "scalar_status": None,
        "profile": None,
        "scoring_engine": None,
        "source": str(source),
        "provisional": flow_status == "ongoing",
    }
    if result.status != "available" or result.data is None:
        return record
    report = result.data
    try:
        invalid = bool(validate_report(report))
    except (TypeError, ValueError, OverflowError):
        invalid = True
    if invalid:
        record["availability"] = "invalid"
        return record
    summary = report["scalar_summary"]
    try:
        identity_matches = Path(report["workspace"]).resolve() == root.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        identity_matches = False
    if not identity_matches:
        record["availability"] = "identity_mismatch"
        return record
    record.update(
        scalar_status=summary["status"],
        profile=summary["profile"],
        scoring_engine=report["scoring_engine"],
    )
    states = {step["name"]: step["state"] for step in steps}
    if (
        flow_status in {"missing", "invalid", "oversized"}
        or len(states) != len(steps)
        or report["flow_steps"] != states
    ):
        record["availability"] = "stale"
    elif summary["score"] is None or summary["status"] == "NOT_RATED":
        record["availability"] = "not_rated"
    else:
        record["score"] = summary["score"]
    return record


def build_project_matrix(manifest: ProjectManifest) -> dict:
    columns = {}
    rows = []
    warnings = []
    for workspace in manifest.workspaces:
        root = Path(workspace.workspace_path)
        steps, flow_status = _flow(root)
        qor = _qor(root, steps, flow_status)
        if flow_status in {"missing", "invalid", "oversized"}:
            warnings.append(f"{workspace.workspace_id}: flow {flow_status}")
        if qor["availability"] != "available":
            warnings.append(f"{workspace.workspace_id}: QoR {qor['availability']}")
        cells = []
        for step in steps:
            identity = (step["name"], step["tool"])
            columns.setdefault(
                identity,
                {
                    "step": step["name"],
                    "token": normalize_step_name(step["name"]),
                    "tool": step["tool"],
                },
            )
            category = flow_category(step).value
            state = normalize_state(step["state"])
            checker = (
                checker_evidence(root, step, manifest.design_name)
                if category == FlowStepCategory.CHECKER.value
                else None
            )
            if checker is not None and checker["availability"] not in {
                "available",
                "not_applicable",
            }:
                warnings.append(
                    f"{workspace.workspace_id}: {step['name']} checker {checker['availability']}"
                )
            cells.append(
                {
                    "step": step["name"],
                    "tool": step["tool"],
                    "state": state,
                    "category": category,
                    "checker": checker,
                    "checklist_status": (
                        step.get("checklist_status", {}).get("status")
                        if isinstance(step.get("checklist_status"), dict)
                        else None
                    ),
                    "checklist_blocked": bool(step.get("checklist_status", {}).get("blocked"))
                    if isinstance(step.get("checklist_status"), dict)
                    else False,
                    "checklist_failed_items": (
                        step.get("checklist_status", {}).get("failed_items", [])
                        if isinstance(step.get("checklist_status"), dict)
                        else []
                    ),
                }
            )
        rows.append(
            {
                "workspace_id": workspace.workspace_id,
                "workspace": str(root),
                "manifest_status": workspace.status,
                "flow_status": flow_status,
                "qor": qor,
                "steps": cells,
            }
        )
    rows.sort(key=lambda row: (row["qor"]["score"] is None, -(row["qor"]["score"] or 0)))
    rank = 0
    for row in rows:
        if row["qor"]["score"] is not None:
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = None
    profiles = {
        (row["qor"]["scoring_engine"], row["qor"]["profile"])
        for row in rows
        if row["qor"]["score"] is not None
    }
    if len(profiles) > 1:
        warnings.append(
            "Scores use different profiles; numeric ordering is not a comparable design ranking."
        )
    return {
        "report": "project",
        "schema_version": 1,
        "project": manifest.project_dir,
        "design": manifest.design_name,
        "status": "partial" if warnings else "available",
        "sort": "qor_score_descending_missing_last_manifest_order_ties",
        "columns": list(columns.values()),
        "workspaces": rows,
        "warnings": warnings,
    }
