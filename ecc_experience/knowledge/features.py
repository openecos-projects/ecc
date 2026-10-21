"""Read stage-visible facts from immutable, digest-checked case evidence."""

import math
from pathlib import Path

from ecc_experience.files import SMALL_EVIDENCE_LIMIT, read_json, safe_child
from ecc_experience.knowledge.recommend import _sanitize
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_integrity
from ecc_experience.models import ExperienceCase, ExperienceError

FEATURE_SCHEMA = "ecc-experience-features/1"


def case_features(case_id: str, store: str | Path, *, through_step: str | None = None) -> dict:
    repository = ExperienceStore(store)
    case = repository.read(case_id)
    directory = repository.case_directory(case_id)
    return extract_features(case, directory, through_step=through_step)


def extract_features(
    case: ExperienceCase, directory: Path, *, through_step: str | None = None
) -> dict:
    steps, specification, artifacts = _sections(case.facts)
    names = [step["name"] for step in steps]
    if through_step is not None:
        if through_step not in names:
            raise _invalid("Requested step is absent from the case flow")
        steps = steps[: names.index(through_step) + 1]
    result = {
        "schema": FEATURE_SCHEMA,
        "case_id": case.case_id,
        "snapshot_digest": case.source.snapshot_digest,
        "through_step": through_step,
        "visibility": "flow_prefix" if through_step else "complete_observation",
        "status": "unknown",
        "steps": [],
        "parameters": {
            "level": case.parameter_evidence,
            "values": _sanitize(specification.get("parameters", {})),
            "scope": "committed_configuration_not_historical_tool_consumption",
        },
        "process": _sanitize(specification.get("pdk", {})),
        "process_fingerprint": case.process_fingerprint,
        "input_content_fingerprint": case.input_content_fingerprint,
        "limitations": [
            "Earlier-stage facts exclude later metrics and final QoR",
            "Configured parameters do not prove materialization or effective consumption",
            "Report hashes bind captured evidence, not original execution or complete PDK closure",
            "Stage resource observations may describe reused attempts; do not sum them as new cost",
        ],
    }
    failures = [
        item.model_dump() for item in verify_integrity(case, directory) if item.status == "fail"
    ]
    if failures:
        return {**result, "status": "fail", "findings": failures}
    evidence = {item.reference: item for item in case.evidence}
    for step in steps:
        entry = {
            "step": step["name"],
            "tool": step.get("tool"),
            "state": step.get("state", "unknown"),
            "metrics": [],
            "status": "unknown",
            "resource_observation": step.get("resource_observation"),
            "analysis_context": None,
            "tool_identity": None,
            "analysis_revision": None,
        }
        reports = [
            item
            for item in artifacts
            if item.get("stepId") == step["name"] and item.get("kind") == "qor_metrics"
        ]
        for artifact in reports:
            captured = evidence.get(artifact["reference"])
            if captured is None or captured.status != "available" or captured.stored_path is None:
                continue
            payload = read_json(safe_child(directory, captured.stored_path), SMALL_EVIDENCE_LIMIT)
            if (
                payload.get("schema_version") != 3
                or payload.get("step") != step["name"]
                or str(payload.get("tool", "")).casefold() != str(step.get("tool", "")).casefold()
                or not isinstance(payload.get("integrity"), dict)
                or payload["integrity"].get("status") != "pass"
                or payload.get("status") != "success"
                or not isinstance(payload.get("metrics"), list)
                or not all(isinstance(item, dict) for item in payload["metrics"])
            ):
                entry["reason"] = "Unsupported or inconsistent stage report"
                continue
            entry["analysis_context"] = payload.get("context")
            entry["analysis_revision"] = payload.get("analysis_revision")
            entry["tool_identity"] = _tool_identity(case, str(step.get("tool", "")))
            integrity = payload.get("integrity", {})
            if not isinstance(integrity.get("invalid_metric_source_ids", []), list):
                entry["reason"] = "Invalid metric integrity metadata"
                continue
            for metric in payload.get("metrics", []):
                value = metric.get("value")
                if not isinstance(metric.get("id"), str) or not isinstance(metric.get("unit"), str):
                    continue
                if any(
                    metric.get(key) is not None and not isinstance(metric[key], str)
                    for key in ("scope", "corner", "category", "direction")
                ):
                    continue
                available = (
                    type(value) in {int, float}
                    and math.isfinite(value)
                    and metric.get("id") not in integrity.get("invalid_metric_source_ids", [])
                )
                entry["metrics"].append(
                    {
                        "id": metric["id"],
                        "value": value if available else None,
                        "unit": metric["unit"],
                        "status": "available" if available else "unavailable",
                        "scope": metric.get("scope"),
                        "corner": metric.get("corner"),
                        "direction": metric.get("direction"),
                        "category": metric.get("category"),
                        "provenance": {
                            "reference": captured.reference,
                            "sha256": captured.sha256,
                            "selector": metric.get("source"),
                        },
                    }
                )
            entry["status"] = "available" if entry["metrics"] else "unknown"
        result["steps"].append(entry)
    if result["steps"] and all(item["status"] == "available" for item in result["steps"]):
        result["status"] = "available"
    elif any(item["status"] == "available" for item in result["steps"]):
        result["status"] = "partial"
    return result


def _sections(facts: dict) -> tuple[list[dict], dict, list[dict]]:
    flow = facts.get("flow", {})
    specification = facts.get("workspaceSpec", {})
    artifacts = facts.get("artifacts", [])
    if not isinstance(flow, dict) or not isinstance(specification, dict):
        raise _invalid("Invalid feature source sections")
    steps = flow.get("steps", [])
    if (
        not isinstance(steps, list)
        or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in steps)
        or not isinstance(artifacts, list)
        or not all(
            isinstance(item, dict) and isinstance(item.get("reference"), str) for item in artifacts
        )
    ):
        raise _invalid("Invalid feature source steps or artifacts")
    if len({item["name"] for item in steps}) != len(steps):
        raise _invalid("Ambiguous duplicate flow step names")
    return steps, specification, artifacts


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_features_invalid")


def _tool_identity(case: ExperienceCase, tool: str) -> dict | None:
    context = case.facts.get("experienceExecutionContext")
    if (
        not isinstance(context, dict)
        or context.get("schema") != "ecc-experience-execution-context/1"
        or context.get("attempt_id") != case.source.attempt_id
        or not isinstance(context.get("runtime"), dict)
    ):
        return None
    runtime = context["runtime"]
    if not isinstance(runtime, dict):
        return None
    sources = runtime.get("sources")
    versions = runtime.get("tools")
    native = runtime.get("native_packages")
    if (
        not isinstance(sources, dict)
        or not sources
        or not isinstance(versions, dict)
        or not isinstance(native, dict)
    ):
        return None
    distribution = {"ecc": "ecc-tools-bin", "dreamplace": "ecc-dreamplace"}.get(tool)
    version = native.get(distribution) if distribution else versions.get(tool)
    if not isinstance(version, str) or version in {"", "unknown", "not installed"}:
        return None
    return {"tool": tool, "version": version, "ecc_sources": sources, "ecc": runtime.get("ecc")}
