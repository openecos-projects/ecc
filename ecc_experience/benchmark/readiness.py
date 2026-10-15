"""Check whether a measured matrix is ready for model or recipe evaluation."""

import json
from pathlib import Path

from ecc_experience.benchmark.matrix import read_report


def check(
    matrix: str | Path,
    output: str | Path,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    min_candidate_configurations: int = 2,
) -> dict:
    if min_independent_designs < 1 or min_families < 1 or min_candidate_configurations < 1:
        raise ValueError("Readiness thresholds must be positive")
    report = read_report(matrix)
    destination = Path(output).expanduser().absolute()
    if destination.exists():
        raise ValueError("Readiness output must be new")
    observations = report["observations"]
    checks = {
        "matrix_status": {
            "status": "pass" if report.get("status") == "unknown" else report.get("status"),
            "observed": report.get("status"),
            "required": "unknown_or_pass",
        },
        "independent_designs": _threshold(
            report.get("independent_input_count", 0), min_independent_designs
        ),
        "families": _threshold(report.get("family_count", 0), min_families),
        "candidate_variation": _threshold(
            max(
                report.get("candidate_variation", {}).get("configurations_by_input", {}).values(),
                default=0,
            ),
            min_candidate_configurations,
        ),
        "verified_observations": _count_check(
            observations,
            lambda row: row.get("verification") == "pass" and row.get("integrity") == "pass",
        ),
        "qor": _count_check(
            observations, lambda row: isinstance(row.get("qor_score"), (int, float))
        ),
        "process": _uniform_check(observations, "process_fingerprint"),
        "runtime": _count_check(observations, lambda row: row.get("runtime_recorded") is True),
    }
    failures = [name for name, item in checks.items() if item["status"] == "fail"]
    unknown = [name for name, item in checks.items() if item["status"] == "unknown"]
    status = (
        "fail" if report.get("status") == "fail" or failures else "unknown" if unknown else "pass"
    )
    result = {
        "schema": "ecc-experience-benchmark-readiness/1",
        "status": status,
        "exit_code": 6 if status == "fail" else 7 if status == "unknown" else 0,
        "matrix": str(Path(matrix).expanduser().resolve()),
        "thresholds": {
            "min_independent_designs": min_independent_designs,
            "min_families": min_families,
            "min_candidate_configurations": min_candidate_configurations,
        },
        "checks": checks,
        "blocking_checks": failures + unknown,
        "generalization_status": "ready_for_review" if status == "pass" else "unproven",
        "safe_to_apply": False,
    }
    destination.mkdir(parents=True)
    (destination / "readiness.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# ECC benchmark readiness",
        "",
        f"Status: {status}; generalization: {result['generalization_status']}",
        "",
        "| Check | Status | Observed | Required |",
        "| --- | --- | --- | --- |",
    ]
    for name, item in checks.items():
        lines.append(
            f"| {name} | {item['status']} | {item.get('observed', '')} | "
            f"{item.get('required', '')} |"
        )
    lines.append("")
    (destination / "readiness.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def _threshold(value: object, minimum: int) -> dict:
    if not isinstance(value, int) or isinstance(value, bool):
        return {"status": "unknown", "observed": value, "required": minimum}
    return {
        "status": "pass" if value >= minimum else "unknown",
        "observed": value,
        "required": minimum,
    }


def _count_check(rows: list[dict], predicate) -> dict:
    count = sum(predicate(row) for row in rows)
    return {
        "status": "pass" if rows and count == len(rows) else "unknown",
        "observed": count,
        "required": len(rows),
    }


def _uniform_check(rows: list[dict], key: str) -> dict:
    values = {row.get(key) for row in rows if isinstance(row.get(key), str) and row.get(key)}
    return {
        "status": "pass" if rows and len(values) == 1 else "unknown",
        "observed": sorted(values),
        "required": "one process fingerprint",
    }
