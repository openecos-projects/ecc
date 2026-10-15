"""Aggregate real design-matrix observations without treating smoke data as model evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path


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


def aggregate(
    inputs: Path,
    expected: list[str],
    output: Path,
    families: dict[str, str] | None = None,
) -> dict:
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("Expected designs must be unique and nonempty")
    if families is not None:
        if not isinstance(families, dict):
            raise ValueError("Family labels must be a JSON object")
        if set(families) - set(expected):
            raise ValueError("Family labels contain an unexpected design")
        if any(not isinstance(name, str) or not name for name in families.values()):
            raise ValueError("Family labels must be nonempty strings")
    if output.exists():
        raise FileExistsError("Matrix report output must be new")
    rows = []
    seen = set()
    failures = []
    for design in expected:
        if not isinstance(design, str) or Path(design).name != design or design in {".", ".."}:
            raise ValueError("Design IDs must be safe path components")
        directory = inputs / design
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
        if not isinstance(facts, dict):
            raise ValueError(f"Observation facts are invalid: {design}")
        context = facts.get("experienceExecutionContext", {})
        qor = facts.get("qorSnapshotExtension", {})
        if not isinstance(context, dict) or not isinstance(qor, dict):
            raise ValueError(f"Observation facts are invalid: {design}")
        if not isinstance(features.get("steps", []), list):
            raise ValueError(f"Observation features are invalid: {design}")
        feature_parameters = features.get("parameters", {})
        parameters = (
            feature_parameters.get("values") if isinstance(feature_parameters, dict) else None
        )
        if not isinstance(parameters, dict):
            parameters = None
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
                "parameters": parameters,
                "steps": features.get("steps", []),
                "family": families.get(design) if families else None,
                "source_sha256": _observation_digest(directory),
            }
        )
    corrupt = any(row["integrity"] == "fail" or row["verification"] == "fail" for row in rows)
    resources = _resource_summary(rows)
    candidate_variation = _candidate_variation(rows)
    missing_families = [row["design"] for row in rows if row["family"] is None]
    status = "fail" if corrupt or failures else "unknown"
    result = {
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
            "or current environment",
            "A single baseline per design cannot establish candidate ranking or convergence gains",
            "Candidate variation is unknown until one input has multiple measured configurations",
            "Resource values retain their scope and are not combined across scopes",
            "Use recorded campaigns, explicit family labels, dataset split and model validate "
            "before promotion",
        ],
    }
    output.mkdir(parents=True)
    (output / "matrix-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# Real ECC CI design matrix",
        "",
        f"Status: {status}; generalization: unproven",
        "",
        "| Design | Verified | Integrity | QoR | Independent input | Runtime recorded |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        values = [
            row["design"],
            row["verification"],
            row["integrity"],
            row["qor_score"],
            bool(row["input_content_fingerprint"]) and not row["duplicate_input"],
            row["runtime_recorded"],
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(["", *result["limitations"], ""])
    lines.extend(
        [
            f"Families: {result['family_count']}; missing labels: {len(missing_families)}",
            f"Candidate variation: {candidate_variation['status']}",
            "",
        ]
    )
    (output / "matrix-report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def _observation_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in ("show", "verify", "features"):
        path = directory / f"{name}.stdout.json"
        try:
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError as exc:
            raise ValueError(f"Invalid CLI observation: {directory.name}/{name}") from exc
    return digest.hexdigest()


def _candidate_variation(rows: list[dict]) -> dict:
    groups: dict[str, set[str]] = {}
    for row in rows:
        fingerprint = row.get("input_content_fingerprint")
        parameters = row.get("parameters")
        if not isinstance(fingerprint, str) or not fingerprint or not isinstance(parameters, dict):
            continue
        groups.setdefault(fingerprint, set()).add(
            json.dumps(parameters, sort_keys=True, ensure_ascii=False)
        )
    varied = {fingerprint: len(values) for fingerprint, values in groups.items() if len(values) > 1}
    return {
        "status": "available" if varied else "unknown",
        "input_groups": len(groups),
        "varied_input_groups": len(varied),
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
                        "elapsed_seconds": _finite_value(observation.get("elapsed_seconds")),
                        "peak_rss_bytes": _finite_value(observation.get("peak_rss_bytes")),
                    }
                )
            else:
                observations.append(
                    {
                        "status": "legacy",
                        "scope": "legacy_flow_step_ledger",
                        "elapsed_seconds": None,
                        "peak_rss_bytes": None,
                    }
                )
                scopes.add("legacy_flow_step_ledger")
        result[name] = {
            "observation_count": len(observations),
            "available_count": sum(item["status"] == "available" for item in observations),
            "scopes": sorted(scopes),
            "observations": observations,
        }
    return result


def _finite_value(value: object) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expected-designs-json", required=True)
    parser.add_argument(
        "--families-json",
        type=Path,
        help="Optional JSON object mapping design IDs to manually declared family labels",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected_designs_json)
    if not isinstance(expected, list):
        parser.error("Expected designs must be a JSON array")
    families = None
    if args.families_json is not None:
        try:
            families = json.loads(args.families_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parser.error(f"Invalid family labels JSON: {exc}")
        if not isinstance(families, dict):
            parser.error("Family labels must be a JSON object")
    try:
        report = aggregate(args.inputs, expected, args.output, families)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "fail", "reason": str(exc)}))
        return 6
    print(json.dumps(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
