"""Aggregate real design-matrix observations without treating smoke data as model evidence."""

import argparse
import hashlib
import json
from pathlib import Path


def _record(directory: Path, name: str) -> dict:
    payload = json.loads((directory / f"{name}.stdout.json").read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError(f"Invalid CLI observation: {directory.name}/{name}")
    return payload[0]


def aggregate(inputs: Path, expected: list[str], output: Path) -> dict:
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("Expected designs must be unique and nonempty")
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
        if verification.get("case_id") != case.get("case_id") or features.get(
            "case_id"
        ) != case.get("case_id"):
            raise ValueError("Observation files refer to different cases")
        fingerprint = case.get("input_content_fingerprint")
        duplicate = bool(fingerprint and fingerprint in seen)
        if fingerprint:
            seen.add(fingerprint)
        facts = case.get("facts", {})
        context = facts.get("experienceExecutionContext", {})
        qor = facts.get("qorSnapshotExtension", {})
        rows.append(
            {
                "design": design,
                "case_id": case["case_id"],
                "input_content_fingerprint": fingerprint,
                "duplicate_input": duplicate,
                "verification": verification.get("status", "unknown"),
                "integrity": verification.get("integrity", "unknown"),
                "process_fingerprint": case.get("process_fingerprint"),
                "runtime_recorded": bool(context.get("runtime")),
                "qor_score": qor.get("score") if qor.get("status") == "available" else None,
                "steps": features.get("steps", []),
                "family": None,
                "source_sha256": hashlib.sha256(
                    (directory / "show.stdout.json").read_bytes()
                ).hexdigest(),
            }
        )
    corrupt = any(row["integrity"] == "fail" or row["verification"] == "fail" for row in rows)
    status = "fail" if corrupt or failures else "unknown"
    result = {
        "schema": "ecc-experience-ci-design-matrix/1",
        "status": status,
        "exit_code": 6 if status == "fail" else 7,
        "expected_designs": expected,
        "observed_design_count": len(rows),
        "independent_input_count": len(seen),
        "observations": rows,
        "failures": failures,
        "generalization_status": "unproven",
        "safe_to_apply": False,
        "limitations": [
            "Only real collected cases are aggregated; synthetic model smoke fixtures are excluded",
            "Family labels and historical runtime are never inferred from a design name "
            "or current environment",
            "A single baseline per design cannot establish candidate ranking or convergence gains",
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
    (output / "matrix-report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expected-designs-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected_designs_json)
    if not isinstance(expected, list):
        parser.error("Expected designs must be a JSON array")
    try:
        report = aggregate(args.inputs, expected, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "fail", "reason": str(exc)}))
        return 6
    print(json.dumps(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
