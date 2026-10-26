"""Summarize experience-store quality and resource observations."""

import json
import math
from collections import Counter
from pathlib import Path

from ecc_experience.files import digest
from ecc_experience.knowledge.configuration import configuration_identity
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import (
    ExperienceCase,
    ExperienceError,
    Verification,
)

SUMMARY_SCHEMA = "ecc-experience-store-summary/1"
_QUALITY_CLASSES = (
    "verified_pass",
    "verified_observation",
    "blocked",
    "qor_unknown",
    "incomplete",
    "evidence_invalid",
)


def summarize_store(store: str | Path, output: str | Path | None = None) -> dict:
    repository = ExperienceStore(store)
    destination = Path(output).expanduser().resolve() if output is not None else None
    if destination is not None and destination.is_relative_to(repository.root):
        raise ExperienceError(
            "Summary output must be outside the source store", code="experience_summary_invalid"
        )
    rows = []
    errors = []
    for case_id in repository.list_ids():
        try:
            case = repository.read(case_id)
            verification = verify_case(case, repository.case_directory(case_id))
            rows.append(summarize_case(case, verification))
        except (ExperienceError, OSError) as exc:
            errors.append({"case_id": case_id, "status": "fail", "reason": str(exc)})

    quality_counts = Counter(row["quality_class"] for row in rows)
    status = (
        "fail"
        if errors or quality_counts["evidence_invalid"]
        else "unknown"
        if not rows or any(not row["release_eligible"] for row in rows)
        else "pass"
    )
    report = {
        "schema": SUMMARY_SCHEMA,
        "status": status,
        "exit_code": 6 if status == "fail" else 7 if status == "unknown" else 0,
        "store": str(repository.root),
        "counts": {
            "cases": len(rows),
            "read_errors": len(errors),
            "quality": {name: quality_counts.get(name, 0) for name in _QUALITY_CLASSES},
            "release_eligible": sum(row["release_eligible"] for row in rows),
        },
        "deduplication": _deduplication(rows),
        "design_bands": _design_bands(rows),
        "processes": _processes(rows),
        "steps": _step_summary(rows),
        "release_eligible_case_ids": sorted(
            row["case_id"] for row in rows if row["release_eligible"]
        ),
        "cases": rows,
        "errors": errors,
        "limitations": [
            "Quality classes separate valid negative observations from evidence corruption",
            "A verified case is release eligible only when flow, signoff and QoR are complete",
            "Configuration groups require matching input, process, parameters, runtime and flow",
            "Runtime and memory retain the scope recorded by each step observation",
            "This report does not infer parameter causality or automatic optimization policy",
        ],
    }
    if destination is not None:
        _write_report(destination, report)
        report["output"] = str(destination)
    return report


def summarize_case(case: ExperienceCase, verification: Verification) -> dict:
    facts = case.facts
    flow_status, checklist_status, step_rows = _flow_summary(facts)
    signoff_status = _signoff_status(facts)
    qor_status, qor_score = _qor(facts)
    quality_class = _quality_class(
        verification, flow_status, checklist_status, signoff_status, qor_status
    )
    parameters = _parameters(facts)
    process = _process(facts)
    cell_count = _cell_count(facts)
    specification = facts.get("workspaceSpec")
    design = specification.get("design") if isinstance(specification, dict) else None
    design_name = None
    if isinstance(design, dict):
        design_name = design.get("name") or design.get("topModule")
    input_fingerprint = case.input_content_fingerprint
    configuration = configuration_identity(case)
    pdk_family = process.get("familyId") or process.get("name")
    return {
        "case_id": case.case_id,
        "design": design_name if isinstance(design_name, str) else None,
        "workspace_id": case.source.workspace_id,
        "workspace_revision": case.source.workspace_revision,
        "validation_scope": case.validation_scope,
        "verification": verification.status,
        "integrity": verification.integrity,
        "quality_class": quality_class,
        "release_eligible": quality_class == "verified_pass"
        and bool(input_fingerprint)
        and isinstance(specification, dict),
        "flow_status": flow_status,
        "checklist_status": checklist_status,
        "signoff_status": signoff_status,
        "qor_status": qor_status,
        "qor_score": qor_score,
        "cell_count": cell_count,
        "design_band": _design_band(cell_count),
        "pdk_family": pdk_family if isinstance(pdk_family, str) else None,
        "process_fingerprint": case.process_fingerprint,
        "parameter_evidence": case.parameter_evidence.model_dump()
        if not isinstance(case.parameter_evidence, str)
        else case.parameter_evidence,
        "parameter_digest": digest(parameters) if parameters else None,
        "input_content_fingerprint": input_fingerprint,
        "dedupe_key": configuration["key"],
        "configuration_complete": configuration["complete"],
        "steps": step_rows,
        "finding_counts": dict(Counter(item.status for item in verification.findings)),
        "findings": [
            item.model_dump(exclude_none=True)
            for item in verification.findings
            if item.status != "pass"
        ],
    }


def _quality_class(
    verification: Verification,
    flow_status: str,
    checklist_status: str,
    signoff_status: str,
    qor_status: str,
) -> str:
    if verification.status == "fail" or verification.integrity == "fail":
        return "evidence_invalid"
    if flow_status in {"failed", "blocked"} or checklist_status in {"failed", "blocked"}:
        return "blocked"
    if signoff_status in {"failed", "blocked"}:
        return "blocked"
    if qor_status != "available":
        return "qor_unknown"
    if (
        verification.status == "pass"
        and flow_status == "success"
        and checklist_status == "passed"
        and signoff_status == "ready"
    ):
        return "verified_pass"
    if verification.status == "pass":
        return "verified_observation"
    return "incomplete"


def _flow_summary(facts: dict) -> tuple[str, str, list[dict]]:
    flow = facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list) or not steps:
        return "unknown", "unknown", []
    states = []
    checklist_states = []
    rows = []
    for step in steps:
        if not isinstance(step, dict):
            states.append("unknown")
            checklist_states.append("unknown")
            continue
        state = _normalize_status(step.get("state"))
        checklist = step.get("checklist_status")
        checklist_state = (
            _normalize_status(checklist.get("status")) if isinstance(checklist, dict) else "unknown"
        )
        states.append(state)
        checklist_states.append(checklist_state)
        observation = step.get("resource_observation")
        elapsed = (
            _nonnegative(observation.get("elapsed_seconds"))
            if isinstance(observation, dict)
            else None
        )
        peak = (
            _nonnegative(observation.get("peak_rss_bytes"))
            if isinstance(observation, dict)
            else None
        )
        memory_scope = observation.get("scope") if isinstance(observation, dict) else None
        if peak is None:
            memory_mb = _nonnegative(step.get("peak memory (mb)"))
            peak = _finite(memory_mb * 1024 * 1024) if memory_mb is not None else None
            memory_scope = "legacy_peak_memory_mb" if peak is not None else None
        rows.append(
            {
                "name": step.get("name"),
                "tool": step.get("tool"),
                "status": state,
                "checklist_status": checklist_state,
                "elapsed_seconds": elapsed,
                "peak_rss_bytes": peak,
                "memory_scope": memory_scope if isinstance(memory_scope, str) else "unknown",
                "resource_observation": observation,
            }
        )
    return (
        _aggregate_status(states, success="success"),
        _aggregate_status(checklist_states, success="passed"),
        rows,
    )


def _aggregate_status(states: list[str], *, success: str) -> str:
    if not states:
        return "unknown"
    if any(state in {"blocked", "failed"} for state in states):
        return "blocked" if "blocked" in states else "failed"
    if all(state == success for state in states):
        return "success" if success == "success" else "passed"
    if any(state in {"running", "ongoing"} for state in states):
        return "running"
    return "incomplete"


def _signoff_status(facts: dict) -> str:
    value = facts.get("signoffAssessment")
    if not isinstance(value, dict):
        return "unknown"
    status = _normalize_status(value.get("status"))
    return {"success": "ready", "passed": "ready", "failed": "failed"}.get(status, status)


def _qor(facts: dict) -> tuple[str, float | None]:
    value = facts.get("qorSnapshotExtension")
    if not isinstance(value, dict) or value.get("status") != "available":
        return "unavailable", None
    score = _finite(value.get("score"))
    return ("available", score) if score is not None else ("unavailable", None)


def _parameters(facts: dict) -> dict:
    specification = facts.get("workspaceSpec")
    parameters = specification.get("parameters") if isinstance(specification, dict) else None
    return parameters if isinstance(parameters, dict) else {}


def _process(facts: dict) -> dict:
    specification = facts.get("workspaceSpec")
    process = specification.get("pdk") if isinstance(specification, dict) else None
    return process if isinstance(process, dict) else {}


def _cell_count(facts: dict) -> int | float | None:
    metrics = facts.get("metrics")
    if not isinstance(metrics, list):
        return None
    for wanted in ("synthesis_cell_count", "instance_count", "std_cell_count"):
        for metric in metrics:
            if isinstance(metric, dict) and metric.get("id") == wanted:
                value = _nonnegative(metric.get("value"))
                if value is not None:
                    return value
    return None


def _design_band(cell_count: int | float | None) -> str:
    if cell_count is None:
        return "unknown"
    if cell_count <= 20_000:
        return "small"
    if cell_count <= 100_000:
        return "medium"
    return "large"


def _deduplication(rows: list[dict]) -> dict:
    groups: dict[str, list[str]] = {}
    for row in rows:
        groups.setdefault(row["dedupe_key"], []).append(row["case_id"])
    duplicate_groups = [values for values in groups.values() if len(values) > 1]
    return {
        "configuration_groups": len(groups),
        "unique_cases": len(rows),
        "duplicate_cases": sum(len(values) - 1 for values in duplicate_groups),
        "duplicate_groups": [sorted(values) for values in duplicate_groups],
    }


def _design_bands(rows: list[dict]) -> dict:
    result = {}
    for band in ("small", "medium", "large", "unknown"):
        members = [row for row in rows if row["design_band"] == band]
        scores = [
            row["qor_score"]
            for row in members
            if row["qor_score"] is not None and row["quality_class"] != "evidence_invalid"
        ]
        result[band] = {
            "cases": len(members),
            "release_eligible": sum(row["release_eligible"] for row in members),
            "qor_available": len(scores),
            "qor_score_min": min(scores) if scores else None,
            "qor_score_max": max(scores) if scores else None,
            "qor_score_average": _average(scores),
        }
    return result


def _processes(rows: list[dict]) -> dict:
    return dict(sorted(Counter(row["pdk_family"] or "unknown" for row in rows).items()))


def _step_summary(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if row["quality_class"] == "evidence_invalid":
            continue
        for step in row["steps"]:
            name = step.get("name")
            if isinstance(name, str) and name:
                grouped.setdefault(name, []).append(step)
    result = {}
    for name, observations in sorted(grouped.items()):
        elapsed = [
            item["elapsed_seconds"] for item in observations if item["elapsed_seconds"] is not None
        ]
        peak = [
            item["peak_rss_bytes"] for item in observations if item["peak_rss_bytes"] is not None
        ]
        result[name] = {
            "observations": len(observations),
            "statuses": dict(Counter(item["status"] for item in observations)),
            "checklist_statuses": dict(Counter(item["checklist_status"] for item in observations)),
            "elapsed_seconds": _numeric_summary(elapsed),
            "peak_rss_bytes": _numeric_summary(peak),
            "memory_scopes": dict(Counter(item["memory_scope"] for item in observations)),
        }
    return result


def _numeric_summary(values: list[int | float]) -> dict:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "average": _average(values),
    }


def _average(values: list[int | float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _finite(value: object) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _nonnegative(value: object) -> int | float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _normalize_status(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    normalized = value.strip().casefold().replace("_", " ")
    return {
        "success": "success",
        "succeeded": "success",
        "passed": "passed",
        "pass": "passed",
        "failure": "failed",
        "fail": "failed",
        "error": "failed",
        "blocked": "blocked",
        "ongoing": "ongoing",
        "running": "running",
    }.get(normalized, normalized.replace(" ", "_"))


def _write_report(destination: Path, report: dict) -> None:
    if destination.exists() or destination.is_symlink():
        raise ExperienceError("Summary output already exists", code="experience_summary_conflict")
    destination.mkdir(parents=True)
    (destination / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# ECC experience store summary",
        "",
        f"Status: {report['status']}",
        "",
        "| Quality class | Count |",
        "| --- | ---: |",
    ]
    for name, count in report["counts"]["quality"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            f"Release eligible: {report['counts']['release_eligible']}",
            f"Configuration groups: {report['deduplication']['configuration_groups']}",
            f"Duplicate cases: {report['deduplication']['duplicate_cases']}",
            "",
            "| Design band | Cases | Release eligible | QoR average |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for band, values in report["design_bands"].items():
        lines.append(
            f"| {band} | {values['cases']} | {values['release_eligible']} | "
            f"{values['qor_score_average']} |"
        )
    lines.extend(["", *report["limitations"], ""])
    (destination / "summary.md").write_text("\n".join(lines), encoding="utf-8")
