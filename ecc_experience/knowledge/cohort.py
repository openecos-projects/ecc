"""Bind immutable case evidence to a runtime cohort and step contracts."""

import hashlib
import json
from collections import Counter
from typing import Any

from ecc_experience.files import digest

COHORT_SCHEMA = "ecc-experience-runtime-cohort/1"
CONTRACT_SCHEMA = "ecc-experience-step-contract/1"
KNOWLEDGE_BINDING_SCHEMA = "ecc-experience-knowledge-binding/1"


def knowledge_binding(
    facts: dict[str, Any],
    copies: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Derive immutable cohort and step-contract evidence from a committed case."""
    contracts = step_contracts(facts, copies or {})
    cohort = runtime_cohort(facts, contracts)
    return {
        "schema": KNOWLEDGE_BINDING_SCHEMA,
        "runtime_cohort": cohort,
        "step_contracts": contracts,
    }


def runtime_cohort(
    facts: dict[str, Any],
    contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    context = facts.get("experienceExecutionContext")
    if not isinstance(context, dict):
        return _unknown_cohort("Case has no attempt-bound execution context")
    runtime = context.get("runtime")
    process = context.get("process")
    if not isinstance(runtime, dict):
        return _unknown_cohort("Case has no runtime identity")
    if not isinstance(process, dict) or process.get("status") != "available":
        return _unknown_cohort("Case has no available process identity")
    runtime_fingerprint = digest(runtime)
    process_fingerprint = process.get("fingerprint")
    if not isinstance(process_fingerprint, str) or not process_fingerprint:
        return _unknown_cohort("Case process fingerprint is missing")
    contract_fingerprint = digest(
        [
            {
                "step": item["step"],
                "tool": item["tool"],
                "report_schema": item["report_schema"],
                "analysis_revision": item["analysis_revision"],
                "metrics": item["metrics"],
            }
            for item in contracts
        ]
    )
    identity = {
        "runtime_fingerprint": runtime_fingerprint,
        "process_fingerprint": process_fingerprint,
        "step_contract_fingerprint": contract_fingerprint,
    }
    measurement = _measurement_scopes(facts)
    return {
        "schema": COHORT_SCHEMA,
        "cohort_id": f"cohort-{digest(identity)}",
        "status": "available",
        "runtime_fingerprint": runtime_fingerprint,
        "process_fingerprint": process_fingerprint,
        "step_contract_fingerprint": contract_fingerprint,
        "tool_versions": _mapping(runtime.get("tools")),
        "native_packages": _mapping(runtime.get("native_packages")),
        "ecc_version": runtime.get("ecc") if isinstance(runtime.get("ecc"), str) else None,
        "host_scope": measurement["host_scope"],
        "measurement_scope": measurement["measurement_scope"],
        "measurement_status": measurement["status"],
        "limitations": [
            "Cohort identity binds whole runtime, selected process and step contracts",
            "Host and measurement scope are descriptive and do not prove workload equivalence",
        ],
    }


def step_contracts(facts: dict[str, Any], copies: dict[str, bytes]) -> list[dict[str, Any]]:
    flow = facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list):
        return []
    artifacts = facts.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, list) else []
    result = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("name"), str):
            continue
        name = step["name"]
        tool = step.get("tool") if isinstance(step.get("tool"), str) else None
        evidence = next(
            (
                item
                for item in artifacts
                if isinstance(item, dict)
                and item.get("stepId") == name
                and item.get("kind") == "qor_metrics"
                and isinstance(item.get("reference"), str)
                and item["reference"] in copies
            ),
            None,
        )
        report = _report(copies.get(evidence["reference"]) if evidence else None)
        metrics = _metrics(report)
        identity = {
            "step": name,
            "tool": tool,
            "report_schema": report.get("schema_version") if report else None,
            "analysis_revision": report.get("analysis_revision") if report else None,
            "metrics": metrics,
        }
        result.append(
            {
                "schema": CONTRACT_SCHEMA,
                "step": name,
                "tool": tool,
                "report_schema": identity["report_schema"],
                "analysis_revision": identity["analysis_revision"],
                "metrics": metrics,
                "failure_taxonomy": "failure-taxonomy/1",
                "status": "available"
                if report is not None
                and isinstance(report.get("schema_version"), int)
                and bool(metrics)
                else "unknown",
                "contract_sha256": digest(identity),
                "source_reference": evidence["reference"] if evidence else None,
                "source_sha256": hashlib.sha256(copies[evidence["reference"]]).hexdigest()
                if evidence and evidence["reference"] in copies
                else None,
            }
        )
    return result


def case_knowledge(case: Any) -> dict[str, Any]:
    facts = case.facts if isinstance(case.facts, dict) else {}
    value = facts.get("experienceKnowledge")
    if (
        not isinstance(value, dict)
        or value.get("schema") != KNOWLEDGE_BINDING_SCHEMA
        or not isinstance(value.get("runtime_cohort"), dict)
        or not isinstance(value.get("step_contracts"), list)
    ):
        return {
            "schema": KNOWLEDGE_BINDING_SCHEMA,
            "status": "legacy_unknown",
            "reason": "Case predates or lacks immutable runtime-cohort binding",
            "runtime_cohort": None,
            "step_contracts": [],
        }
    cohort = value["runtime_cohort"]
    return {
        **value,
        "status": "available" if cohort.get("status") == "available" else "legacy_unknown",
    }


def cohort_status(case: Any, active_cohort: str | None = None) -> str:
    knowledge = case_knowledge(case)
    cohort = knowledge.get("runtime_cohort")
    if knowledge["status"] != "available" or not isinstance(cohort, dict):
        return "legacy_unknown"
    cohort_id = cohort.get("cohort_id")
    if not isinstance(cohort_id, str):
        return "unknown"
    if active_cohort is None:
        return "available"
    return "same_cohort" if cohort_id == active_cohort else "cross_cohort"


def _report(content: bytes | None) -> dict[str, Any] | None:
    if content is None:
        return None
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _metrics(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    values = report.get("metrics") if report else None
    if not isinstance(values, list):
        return []
    result = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        result.append(
            {
                "id": item["id"],
                "unit": item.get("unit") if isinstance(item.get("unit"), str) else None,
                "scope": item.get("scope") if isinstance(item.get("scope"), str) else None,
                "corner": item.get("corner") if isinstance(item.get("corner"), str) else None,
            }
        )
    return sorted(result, key=lambda item: (item["id"], item["unit"] or "", item["scope"] or ""))


def _measurement_scopes(facts: dict[str, Any]) -> dict[str, Any]:
    flow = facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else []
    hosts = []
    scopes = Counter()
    statuses = Counter()
    for step in steps if isinstance(steps, list) else []:
        observation = step.get("resource_observation") if isinstance(step, dict) else None
        if not isinstance(observation, dict):
            continue
        host = observation.get("host")
        if isinstance(host, dict):
            hosts.append(host)
        measurement = observation.get("measurement")
        scope = (
            measurement.get("scope") if isinstance(measurement, dict) else observation.get("scope")
        )
        status = measurement.get("status") if isinstance(measurement, dict) else None
        if isinstance(scope, str):
            scopes[scope] += 1
        if isinstance(status, str):
            statuses[status] += 1
    host_scope = digest(hosts[0]) if hosts else None
    measurement_scope = sorted(scopes) if scopes else None
    status = (
        "available"
        if statuses and all(name == "available" for name in statuses)
        else "partial"
        if statuses
        else "unknown"
    )
    return {
        "host_scope": host_scope,
        "measurement_scope": measurement_scope,
        "status": status,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unknown_cohort(reason: str) -> dict[str, Any]:
    return {
        "schema": COHORT_SCHEMA,
        "cohort_id": None,
        "status": "unknown",
        "runtime_fingerprint": None,
        "process_fingerprint": None,
        "step_contract_fingerprint": None,
        "tool_versions": {},
        "native_packages": {},
        "ecc_version": None,
        "host_scope": None,
        "measurement_scope": None,
        "measurement_status": "unknown",
        "reason": reason,
        "limitations": ["A cohort cannot be assigned without complete execution evidence"],
    }
