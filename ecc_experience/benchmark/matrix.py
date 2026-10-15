"""Aggregate real design observations without inferring generalization."""

import hashlib
import json
import math
from pathlib import Path


def aggregate(
    inputs: str | Path,
    expected: list[str],
    output: str | Path,
    families: dict[str, str] | None = None,
) -> dict:
    source = Path(inputs).expanduser().resolve()
    destination = Path(output).expanduser().absolute()
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("Expected designs must be unique and nonempty")
    if families is not None:
        if not isinstance(families, dict):
            raise ValueError("Family labels must be a JSON object")
        if set(families) - set(expected):
            raise ValueError("Family labels contain an unexpected design")
        if any(not isinstance(value, str) or not value for value in families.values()):
            raise ValueError("Family labels must be nonempty strings")
    if destination.exists():
        raise ValueError("Matrix report output must be new")
    rows = []
    seen = set()
    failures = []
    for design in expected:
        if not isinstance(design, str) or Path(design).name != design or design in {".", ".."}:
            raise ValueError("Design IDs must be safe path components")
        directory = source / design
        try:
            case = _record(directory, "show")
            verification = _record(directory, "verify")
            features = _record(directory, "features")
        except FileNotFoundError:
            failures.append({"design": design, "reason": "missing_observation"})
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Observation has no case ID: {design}")
        if verification.get("case_id") != case_id or features.get("case_id") != case_id:
            raise ValueError("Observation files refer to different cases")
        fingerprint = case.get("input_content_fingerprint")
        duplicate = bool(fingerprint and fingerprint in seen)
        if fingerprint:
            seen.add(fingerprint)
        facts = case.get("facts", {})
        context = facts.get("experienceExecutionContext", {}) if isinstance(facts, dict) else None
        qor = facts.get("qorSnapshotExtension", {}) if isinstance(facts, dict) else None
        steps = features.get("steps", [])
        if (
            not isinstance(context, dict)
            or not isinstance(qor, dict)
            or not isinstance(steps, list)
        ):
            raise ValueError(f"Observation facts or features are invalid: {design}")
        feature_parameters = features.get("parameters", {})
        parameters = (
            feature_parameters.get("values") if isinstance(feature_parameters, dict) else None
        )
        rows.append(
            {
                "design": design,
                "case_id": case_id,
                "input_content_fingerprint": fingerprint,
                "duplicate_input": duplicate,
                "verification": verification.get("status", "unknown"),
                "integrity": verification.get("integrity", "unknown"),
                "process_fingerprint": case.get("process_fingerprint"),
                "runtime_recorded": bool(context.get("runtime")),
                "qor_score": qor.get("score") if qor.get("status") == "available" else None,
                "parameters": parameters if isinstance(parameters, dict) else None,
                "steps": steps,
                "family": families.get(design) if families else None,
                "source_sha256": _observation_digest(directory),
            }
        )
    corrupt = any(row["integrity"] == "fail" or row["verification"] == "fail" for row in rows)
    resources = _resource_summary(rows)
    candidate_variation = _candidate_variation(rows)
    missing_families = [row["design"] for row in rows if row["family"] is None]
    status = "fail" if corrupt or failures else "unknown"
    report = {
        "schema": "ecc-experience-ci-design-matrix/1",
        "status": status,
        "exit_code": 6 if status == "fail" else 7,
        "expected_designs": expected,
        "observed_design_count": len(rows),
        "independent_input_count": len(seen),
        "family_count": len({row["family"] for row in rows if row["family"] is not None}),
        "missing_family_designs": missing_families,
        "candidate_variation": candidate_variation,
        "resource_summary": resources,
        "observations": rows,
        "failures": failures,
        "generalization_status": "unproven",
        "safe_to_apply": False,
        "limitations": [
            "Only real collected cases are aggregated; synthetic model smoke fixtures are excluded",
            "Family labels and historical runtime are never inferred from a design name "
            "or environment",
            "A single baseline per design cannot establish candidate ranking or convergence gains",
            "Candidate variation is unknown until one input has multiple measured configurations",
            "Resource values retain their recorded scope and are not combined across scopes",
            "Use explicit families, dataset split and model validation before promotion",
        ],
    }
    destination.mkdir(parents=True)
    (destination / "matrix-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown(destination / "matrix-report.md", report)
    return report


def read_report(path: str | Path) -> dict:
    source = Path(path).expanduser()
    if source.is_dir():
        source = source / "matrix-report.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid matrix report: {source}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "ecc-experience-ci-design-matrix/1"
    ):
        raise ValueError("Invalid matrix report schema")
    if not isinstance(payload.get("observations"), list):
        raise ValueError("Matrix report observations are invalid")
    return payload


def _record(directory: Path, name: str) -> dict:
    try:
        payload = json.loads((directory / f"{name}.stdout.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid CLI observation: {directory.name}/{name}") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError(f"Invalid CLI observation: {directory.name}/{name}")
    return payload[0]


def _observation_digest(directory: Path) -> str:
    checksum = hashlib.sha256()
    for name in ("show", "verify", "features"):
        try:
            checksum.update(name.encode("utf-8"))
            checksum.update((directory / f"{name}.stdout.json").read_bytes())
        except OSError as exc:
            raise ValueError(f"Invalid CLI observation: {directory.name}/{name}") from exc
    return checksum.hexdigest()


def _candidate_variation(rows: list[dict]) -> dict:
    groups: dict[str, set[str]] = {}
    for row in rows:
        fingerprint = row.get("input_content_fingerprint")
        parameters = row.get("parameters")
        if not isinstance(fingerprint, str) or not fingerprint or not isinstance(parameters, dict):
            continue
        groups.setdefault(fingerprint, set()).add(json.dumps(parameters, sort_keys=True))
    return {
        "status": "available" if any(len(values) > 1 for values in groups.values()) else "unknown",
        "input_groups": len(groups),
        "varied_input_groups": sum(len(values) > 1 for values in groups.values()),
        "configurations_by_input": {
            fingerprint: len(values) for fingerprint, values in sorted(groups.items())
        },
    }


def _resource_summary(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        for step in row.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("step"), str):
                grouped.setdefault(step["step"], []).append(step)
    result = {}
    for name, steps in sorted(grouped.items()):
        observations = []
        scopes = set()
        for step in steps:
            observation = step.get("resource_observation")
            if isinstance(observation, dict):
                scope = observation.get("scope")
                if isinstance(scope, str) and scope:
                    scopes.add(scope)
                observations.append(
                    {
                        "status": observation.get("status", "unknown"),
                        "scope": scope,
                        "elapsed_seconds": _finite(observation.get("elapsed_seconds")),
                        "peak_rss_bytes": _finite(observation.get("peak_rss_bytes")),
                    }
                )
            else:
                scopes.add("legacy_flow_step_ledger")
                observations.append(
                    {
                        "status": "legacy",
                        "scope": "legacy_flow_step_ledger",
                        "elapsed_seconds": None,
                        "peak_rss_bytes": None,
                    }
                )
        result[name] = {
            "observation_count": len(observations),
            "available_count": sum(item["status"] == "available" for item in observations),
            "scopes": sorted(scopes),
            "observations": observations,
        }
    return result


def _finite(value: object) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _write_markdown(path: Path, report: dict) -> None:
    lines = [
        "# Real ECC CI design matrix",
        "",
        f"Status: {report['status']}; generalization: unproven",
        "",
        "| Design | Verified | Integrity | QoR | Independent input | Runtime recorded |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["observations"]:
        values = [
            row["design"],
            row["verification"],
            row["integrity"],
            row["qor_score"],
            bool(row["input_content_fingerprint"]) and not row["duplicate_input"],
            row["runtime_recorded"],
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(["", *report["limitations"], ""])
    lines.extend(
        [
            f"Families: {report['family_count']}; "
            f"missing labels: {len(report['missing_family_designs'])}",
            f"Candidate variation: {report['candidate_variation']['status']}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
