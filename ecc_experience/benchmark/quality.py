"""Read-only quality checks across every campaign observation, including retries."""

import math
from collections import Counter
from pathlib import Path

from chipcompiler.cli.core.exit_codes import EXIT_GATE_FAILED, EXIT_GATE_UNKNOWN
from ecc_experience.benchmark.ledger import read_campaign_ledger
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, Finding

_CORE_EVIDENCE = {
    "home/engineering-snapshot.json",
    "home/flow.json",
    "home/checklist.json",
    "home/params.toml",
}


def campaign_quality(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    view = read_campaign_ledger(manifest, ledger)
    repository = ExperienceStore(view.manifest_summary["store"])
    observations = {}
    trials = []
    case_ids = set()
    executions = set()
    fingerprints = set()
    pending = 0
    for design in view.data["designs"]:
        pending += not design["trials"]
        for trial in design["trials"]:
            case_id = trial.get("case_id")
            if case_id not in observations:
                observations[case_id] = _observation(
                    case_id, repository, view.data["process_profile"]
                )
            observation = observations[case_id]
            identity = observation["execution_identity"]
            fingerprint = observation["input_content_fingerprint"]
            trials.append(
                {
                    "design_id": design["id"],
                    "trial_id": trial["trial_id"],
                    "workspace": trial["workspace"],
                    "execution_status": trial["status"],
                    "case_id": case_id,
                    "quality_status": observation["status"],
                    "reused_case": case_id is not None and case_id in case_ids,
                    "reused_execution_identity": identity is not None and identity in executions,
                    **{key: value for key, value in observation.items() if key != "status"},
                }
            )
            if observation["integrity"] == "pass":
                case_ids.add(case_id)
                if identity is not None:
                    executions.add(identity)
                if fingerprint is not None:
                    fingerprints.add(fingerprint)
    counts = dict(Counter(item["quality_status"] for item in trials))
    running = sum(item["execution_status"] == "running" for item in trials)
    status = (
        "fail"
        if counts.get("fail")
        else "unknown"
        if counts.get("unknown") or pending or running
        else "pass"
    )
    groups = {
        item["evaluation_group"] for item in view.data["designs"] if item.get("evaluation_group")
    }
    return {
        "schema_version": 1,
        "kind": "ecc-experience-campaign-quality",
        "campaign_id": view.data["campaign_id"],
        "manifest_fingerprint": view.data["manifest_fingerprint"],
        "ledger": str(view.path),
        "status": status,
        "exit_code": EXIT_GATE_FAILED
        if status == "fail"
        else EXIT_GATE_UNKNOWN
        if status == "unknown"
        else 0,
        "counts": {
            "designs": len(view.data["designs"]),
            "pending_designs": pending,
            "trials": len(trials),
            "running_trials": running,
            "quality": {key: counts.get(key, 0) for key in ("pass", "fail", "unknown")},
            "execution": dict(Counter(item["execution_status"] for item in trials)),
        },
        "coverage": {
            key: {
                "available": sum(item["coverage"][key] for item in trials),
                "total": len(trials),
            }
            for key in ("committed", "attempt", "inputs", "parameters", "process", "qor")
        },
        "diversity": {
            "unique_cases": len(case_ids),
            "unique_execution_identities": len(executions),
            "unique_input_fingerprints": len(fingerprints),
            "duplicate_case_references": sum(item["reused_case"] for item in trials),
            "repeated_execution_references": sum(
                item["reused_execution_identity"] for item in trials
            ),
            "evaluation_groups_provided": len(groups),
            "designs_without_evaluation_group": sum(
                not item.get("evaluation_group") for item in view.data["designs"]
            ),
        },
        "trials": trials,
        "limitations": [
            "Quality checks do not replace flow, checklist, signoff or release acceptance",
            "Input fingerprints are partial; full include and PDK content closure is not verified",
            "Different input fingerprints do not prove independent design families",
            "Execution identities are observed metadata, not proof of independent reruns",
            "Coverage counts trial references; diversity counts identify repeated observations",
            "Optional missing artifacts are counted but do not fail the quality gate",
            "Step runtime and memory retain legacy scope; no calibrated resource model is inferred",
        ],
    }


def _observation(case_id: str | None, repository: ExperienceStore, profile: str) -> dict:
    result = {
        "status": "unknown",
        "integrity": "unknown",
        "verification_status": "unknown",
        "execution_identity": None,
        "input_content_fingerprint": None,
        "coverage": dict.fromkeys(
            ("committed", "attempt", "inputs", "parameters", "process", "qor"), False
        ),
        "findings": [],
        "steps": [],
        "artifact_counts": {},
        "qor": {},
        "process": {},
    }
    if case_id is None:
        result["findings"] = [{"status": "unknown", "check": "case", "reason": "No case recorded"}]
        return result
    try:
        case = repository.read(case_id)
        verification = verify_case(case, repository.case_directory(case_id))
    except FileNotFoundError as exc:
        result["findings"] = [{"status": "unknown", "check": "case", "reason": str(exc)}]
        return result
    except (OSError, ValueError) as exc:
        result.update(status="fail", integrity="fail")
        result["findings"] = [{"status": "fail", "check": "case", "reason": str(exc)}]
        return result
    findings = [item for item in verification.findings if item.status != "pass"]
    coverage = _coverage(case, profile)
    for key, available in coverage.items():
        if not available:
            findings.append(
                Finding(status="unknown", check=key, reason="Required fact unavailable")
            )
    spec = case.facts.get("workspaceSpec")
    pdk = spec.get("pdk") if isinstance(spec, dict) else None
    family = pdk.get("familyId") if isinstance(pdk, dict) else None
    if family and family != profile:
        findings.append(
            Finding(status="fail", check="process", reason="PDK profile differs from manifest")
        )
    qor = case.facts.get("qorSnapshotExtension")
    if isinstance(qor, dict) and qor.get("score") is not None and not _finite_number(qor["score"]):
        findings.append(
            Finding(status="fail", check="qor", reason="QoR score must be a finite number")
        )
    evidence = {item.reference: item for item in case.evidence}
    for reference in sorted(_CORE_EVIDENCE):
        if reference not in evidence or evidence[reference].status != "available":
            findings.append(Finding(status="unknown", check="core_evidence", reference=reference))
    identity = (
        (case.source.workspace_id or case.source.workspace_root, case.source.attempt_id)
        if case.source.attempt_id
        else None
    )
    result.update(
        status="fail"
        if any(item.status == "fail" for item in findings)
        else "unknown"
        if findings
        else "pass",
        integrity=verification.integrity,
        verification_status=verification.status,
        execution_identity=identity,
        input_content_fingerprint=case.input_content_fingerprint,
        coverage=coverage,
        findings=[item.model_dump(exclude_none=True) for item in findings],
        artifact_counts=dict(Counter(item.status for item in case.evidence)),
        steps=_steps(case),
        qor={key: qor[key] for key in ("score", "status", "profile", "scoringEngine") if key in qor}
        if isinstance(qor, dict)
        else {},
        process=pdk if isinstance(pdk, dict) else {},
    )
    return result


def _coverage(case: ExperienceCase, profile: str) -> dict:
    spec = case.facts.get("workspaceSpec")
    pdk = spec.get("pdk") if isinstance(spec, dict) else None
    qor = case.facts.get("qorSnapshotExtension")
    score = qor.get("score") if isinstance(qor, dict) else None
    return {
        "committed": case.validation_scope == "committed_observation"
        and bool(case.source.snapshot_digest),
        "attempt": bool(case.source.attempt_id),
        "inputs": bool(case.input_content_fingerprint)
        and bool(case.inputs)
        and all(item.status == "available" and item.sha256 for item in case.inputs),
        "parameters": case.parameter_evidence == "configured",
        "process": isinstance(pdk, dict) and pdk.get("familyId") == profile,
        "qor": isinstance(qor, dict) and qor.get("status") == "available" and _finite_number(score),
    }


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _steps(case: ExperienceCase) -> list[dict]:
    flow = case.facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list):
        return []
    result = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        memory = step.get("peak memory (mb)")
        result.append(
            {
                "name": step.get("name"),
                "tool": step.get("tool"),
                "state": step.get("state"),
                "checklist_status": step.get("checklist_status"),
                "runtime": step.get("runtime"),
                "peak_memory_mb": memory
                if isinstance(memory, (int, float)) and _finite_number(memory) and memory > 0
                else None,
                "resource_scope": "legacy_flow_step_ledger",
            }
        )
    return result
