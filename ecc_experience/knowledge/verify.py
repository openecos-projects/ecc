from pathlib import Path

from ecc_experience.files import file_digest, safe_child
from ecc_experience.models import ExperienceCase, ExperienceError, Finding, Verification


def _check_file(root: Path, reference: str, checksum: str, size: int) -> Finding:
    try:
        actual = file_digest(safe_child(root, reference))
    except (OSError, ExperienceError) as exc:
        return Finding(status="fail", check="file_digest", reference=reference, reason=str(exc))
    return Finding(
        status="pass" if actual == (checksum, size) else "fail",
        check="file_digest",
        reference=reference,
        reason=None if actual == (checksum, size) else "Evidence content changed",
    )


def verify_integrity(case: ExperienceCase, directory: Path) -> list[Finding]:
    findings = []
    for evidence in case.evidence:
        if evidence.stored_path is None:
            continue
        if evidence.sha256 is None or evidence.bytes is None:
            findings.append(Finding(status="fail", check="manifest", reason="Missing digest"))
            continue
        findings.append(
            _check_file(directory, evidence.stored_path, evidence.sha256, evidence.bytes)
        )
    return findings


def verify_case(case: ExperienceCase, directory: Path) -> Verification:
    findings = verify_integrity(case, directory)
    integrity = "fail" if any(item.status == "fail" for item in findings) else "pass"
    for evidence in case.evidence:
        if evidence.status in {"invalid", "stale"}:
            findings.append(
                Finding(
                    status="fail",
                    check="captured_evidence",
                    reference=evidence.reference,
                    reason=evidence.reason or evidence.status,
                )
            )
    root = Path(case.source.workspace_root)
    if not root.is_dir() or root.is_symlink():
        findings.append(Finding(status="unknown", check="source", reason="Source is unavailable"))
    else:
        for evidence in case.evidence:
            if evidence.status == "unavailable":
                findings.append(
                    Finding(status="unknown", check="source", reference=evidence.reference)
                )
            elif evidence.status == "available":
                if evidence.sha256 is None or evidence.bytes is None:
                    findings.append(
                        Finding(status="fail", check="manifest", reason="Missing digest")
                    )
                else:
                    findings.append(
                        _check_file(root, evidence.reference, evidence.sha256, evidence.bytes)
                    )
    if case.validation_scope == "legacy_import":
        findings.append(
            Finding(
                status="unknown",
                check="commit",
                reason="Legacy workspace has no committed snapshot",
            )
        )
    _identity_findings(case, findings)
    qor = case.facts.get("qorSnapshotExtension")
    if not isinstance(qor, dict) or qor.get("score") is None:
        findings.append(Finding(status="unknown", check="qor", reason="QoR score unavailable"))
    if case.source.attempt_id:
        findings.append(
            Finding(
                status="pass",
                check="execution_identity",
                reference=case.source.attempt_id,
            )
        )
    else:
        findings.append(
            Finding(
                status="unknown",
                check="execution_identity",
                reason="Source has no stable attempt identity",
            )
        )
    statuses = {item.status for item in findings if not item.check.startswith("identity_")}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return Verification(case_id=case.case_id, status=status, integrity=integrity, findings=findings)


def _identity_findings(case: ExperienceCase, findings: list[Finding]) -> None:
    if case.schema_version == 1:
        findings.append(
            Finding(
                status="unknown",
                check="identity_schema",
                reason="Schema v1 case has no normalized design, constraint or closure identity",
            )
        )
        return
    checks = (
        (
            "identity_design",
            case.design is not None
            and case.design.closure == "complete"
            and bool(case.design.fingerprint),
            "Design input closure is partial or unknown" if case.design else "Design is missing",
        ),
        (
            "identity_constraints",
            case.constraints is not None
            and case.constraints.timing_constraints_status == "available"
            and bool(case.constraints.fingerprint),
            "Timing constraints are partial or unknown"
            if case.constraints
            else "Constraints are missing",
        ),
        (
            "identity_process",
            case.process is not None and case.process.status == "available",
            "Selected process identity is partial or unknown"
            if case.process
            else "Process identity is missing",
        ),
        (
            "identity_toolchain",
            case.toolchain is not None and case.toolchain.status == "available",
            "Runtime toolchain identity is unavailable"
            if case.toolchain
            else "Toolchain is missing",
        ),
    )
    for check, passed, reason in checks:
        findings.append(
            Finding(
                status="pass" if passed else "unknown",
                check=check,
                reason=None if passed else reason,
            )
        )
