"""Export all campaign attempts with immutable case evidence and explicit unknowns."""

import csv
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

from ecc_experience.benchmark.ledger import read_campaign_ledger
from ecc_experience.benchmark.quality import campaign_quality
from ecc_experience.files import digest
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan


def report_campaign(
    manifest: str | Path, output: str | Path, ledger: str | Path | None = None
) -> dict:
    view = read_campaign_ledger(manifest, ledger)
    repository = ExperienceStore(view.manifest_summary["store"])
    destination = Path(output).expanduser().absolute()
    protected = [repository.root, Path(view.manifest_summary["output_root"])]
    protected.extend(
        Path(view.manifest_summary["manifest_root"]) / item["input"]
        for item in view.data["designs"]
    )
    if (
        destination.exists()
        or destination.is_symlink()
        or any(
            destination.resolve().is_relative_to(root.resolve())
            or root.resolve().is_relative_to(destination.resolve())
            for root in protected
        )
    ):
        raise ExperienceError(
            "Report output must be new and outside inputs/runs/store",
            code="experience_manifest_invalid",
        )
    rows = []
    for design in view.data["designs"]:
        attempts = design["trials"] or [None]
        for trial in attempts:
            row: dict = {
                "design_id": design["id"],
                "labels": design["labels"],
                "evaluation_group": design.get("evaluation_group"),
                "trial_id": trial["trial_id"] if trial else None,
                "workspace": trial["workspace"] if trial else design["workspace"],
                "status": trial["status"] if trial else "pending",
                "reason": trial.get("reason") if trial else None,
                "case_id": trial.get("case_id") if trial else None,
                "verification": "missing",
                "integrity": "unknown",
                "qor_score": None,
                "parameters": {},
                "steps": [],
                "signoff": {},
                "checker_evidence": {},
            }
            case_id = row["case_id"]
            if isinstance(case_id, str):
                try:
                    case = repository.read(case_id)
                    verification = verify_case(case, repository.case_directory(case.case_id))
                    row.update(verification=verification.status, integrity=verification.integrity)
                    if verification.integrity == "pass":
                        facts: dict = case.facts
                        qor = facts.get("qorSnapshotExtension", {})
                        spec = facts.get("workspaceSpec", {})
                        flow = facts.get("flow", {})
                        if (
                            not isinstance(qor, dict)
                            or not isinstance(spec, dict)
                            or not isinstance(flow, dict)
                        ):
                            raise ExperienceError("Invalid stored case facts")
                        score = qor.get("score")
                        row.update(
                            qor_score=score
                            if qor.get("status") == "available"
                            and isinstance(score, (int, float))
                            and not isinstance(score, bool)
                            and math.isfinite(score)
                            else None,
                            parameters=spec.get("parameters", {}),
                            steps=flow.get("steps", []),
                            signoff=facts.get("signoffAssessment", {}),
                        )
                        features = case_features(case.case_id, repository.root)
                        row["checker_evidence"] = {
                            step["step"]: _checker(step)
                            for step in features["steps"]
                            if step["step"] in {"drc", "lvs", "sta"}
                        }
                except (OSError, ValueError) as exc:
                    row.update(verification="fail", evidence_error=str(exc))
            rows.append(row)
    quality = campaign_quality(manifest, ledger)
    if digest(read_campaign_ledger(manifest, ledger).data) != digest(view.data):
        raise ExperienceError("Campaign changed while reporting", code="experience_source_changed")
    report = {
        "schema": "ecc-experience-campaign-report/1",
        "campaign_id": view.data["campaign_id"],
        "manifest_fingerprint": view.manifest_summary["fingerprint"],
        "ledger_sha256": digest(view.data),
        "quality": quality,
        "rows": rows,
        "step_names": list(dict.fromkeys(step["name"] for row in rows for step in row["steps"])),
        "status": quality["status"],
        "exit_code": quality["exit_code"],
        "generalization_status": "unproven",
        "safe_to_apply": False,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".campaign-report-", dir=destination.parent))
    try:
        write_plan(staging / "matrix.json", report)
        _write_tables(staging, report)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**report, "output": str(destination)}


def _checker(step: dict) -> dict:
    from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY

    keys = {
        "drc": ("drc_count",),
        "lvs": ("lvs_count",),
        "sta": ("sta_setup_violation_count", "sta_hold_violation_count"),
    }[step["step"]]
    counts = {}
    for key in keys:
        found = [metric for metric in step["metrics"] if metric["id"] == key]
        if len(found) != 1:
            continue
        metric = found[0]
        value = metric["value"]
        if (
            metric["status"] == "available"
            and metric["unit"] == METRIC_REGISTRY[key][0]
            and type(value) in (int, float)
            and math.isfinite(value)
            and value >= 0
            and int(value) == value
        ):
            counts[key] = int(value)
    complete = len(counts) == len(keys)
    violated = any(value > 0 for value in counts.values())
    return {
        "status": "violated" if violated else "clean" if complete else "unknown",
        "counts": counts,
        "complete": complete,
        "scope": "stored_step_checker_metrics",
    }


def _cell(step: dict, checker: dict | None) -> str:
    checklist = step.get("checklist_status") or {}
    parts = [str(step.get("state", "unknown")), f"checklist={checklist.get('status', 'unknown')}"]
    if checker:
        parts.append(
            f"checker={checker['status']} counts={json.dumps(checker['counts'], sort_keys=True)}"
        )
    observation = step.get("resource_observation")
    if isinstance(observation, dict):
        parts.append(
            f"elapsed_s={observation.get('elapsed_seconds', 'unknown')} "
            f"peak_rss_bytes={observation.get('peak_rss_bytes', 'unknown')} "
            f"scope={observation.get('scope', 'unknown')} "
            f"resource_status={observation.get('status', 'unknown')}"
        )
    else:
        parts.append(
            f"runtime={step.get('runtime', 'unknown')} "
            f"peak_memory_mb={step.get('peak memory (mb)', 'unknown')} "
            "scope=legacy_flow_step_ledger"
        )
    return "; ".join(parts)


def _write_tables(directory: Path, report: dict) -> None:
    columns = [
        "design_id",
        "trial_id",
        "workspace",
        "status",
        "qor_score",
        "verification",
        "reason",
    ]
    lines = [
        "# ECC campaign matrix",
        "",
        f"Campaign: {report['campaign_id']}",
        "",
        "All attempts are retained. QoR is not a ranking across different designs.",
        "",
        "| " + " | ".join([*columns, *report["step_names"]]) + " |",
        "| " + " | ".join("---" for _ in [*columns, *report["step_names"]]) + " |",
    ]
    with (directory / "matrix.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [*columns, *report["step_names"], "parameters", "steps", "signoff", "checker_evidence"]
        )
        for row in report["rows"]:
            steps = {step["name"]: step for step in row["steps"]}
            values = [row[key] if row[key] is not None else "unknown" for key in columns]
            values.extend(
                _cell(steps[name], row["checker_evidence"].get(name))
                if name in steps
                else "unknown"
                for name in report["step_names"]
            )
            writer.writerow(
                [
                    *values,
                    *[
                        json.dumps(row[key], ensure_ascii=False)
                        for key in ("parameters", "steps", "signoff", "checker_evidence")
                    ],
                ]
            )
            lines.append(
                "| "
                + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in values)
                + " |"
            )
    lines.extend(
        [
            "",
            "matrix.json preserves parameters, checker evidence, resource observations "
            "and their scope, missing evidence and all attempt identities.",
            "",
        ]
    )
    (directory / "matrix.md").write_text("\n".join(lines), encoding="utf-8")
