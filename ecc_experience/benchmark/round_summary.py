"""Create a read-only, auditable summary of one benchmark round."""

import hashlib
import json
from pathlib import Path

from ecc_experience.files import canonical_bytes, digest
from ecc_experience.models import ExperienceError

_SCHEMA_FILES = {
    "ecc-experience-benchmark-plan/1": "benchmark-plan.json",
    "ecc-experience-ci-design-matrix/1": "matrix-report.json",
    "ecc-experience-benchmark-readiness/1": "readiness.json",
    "ecc-experience-campaign-effect/1": "effect.json",
}


def summarize(
    plan: str | Path,
    matrix: str | Path,
    readiness: str | Path,
    output: str | Path,
    effect: str | Path | None = None,
) -> dict:
    plan_payload = _read(plan, "ecc-experience-benchmark-plan/1")
    matrix_payload = _read(matrix, "ecc-experience-ci-design-matrix/1")
    readiness_payload = _read(readiness, "ecc-experience-benchmark-readiness/1")
    effect_payload = _read(effect, "ecc-experience-campaign-effect/1") if effect else None
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ExperienceError(
            "Benchmark summary output must be new", code="experience_benchmark_invalid"
        )
    _check_plan(plan_payload)
    if readiness_payload.get("matrix") and Path(readiness_payload["matrix"]).name not in {
        Path(matrix).name,
        "matrix-report.json",
    }:
        raise ExperienceError(
            "Readiness report does not reference the supplied matrix",
            code="experience_benchmark_invalid",
        )
    statuses = {
        "plan": plan_payload.get("status"),
        "matrix": matrix_payload.get("status"),
        "readiness": readiness_payload.get("status"),
        "effect": effect_payload.get("status") if effect_payload else "not_requested",
    }
    status = _status(statuses)
    artifacts = [_artifact(plan, plan_payload), _artifact(matrix, matrix_payload)]
    artifacts.append(_artifact(readiness, readiness_payload))
    if effect:
        artifacts.append(_artifact(effect, effect_payload or {}))
    result = {
        "schema": "ecc-experience-benchmark-summary/1",
        "status": status,
        "exit_code": 6 if status == "fail" else 7 if status == "unknown" else 0,
        "benchmark_id": plan_payload.get("benchmark_id"),
        "process_profile": plan_payload.get("process_profile"),
        "statuses": statuses,
        "artifacts": artifacts,
        "plan": {
            "spec_sha256": plan_payload.get("spec_sha256"),
            "plan_sha256": plan_payload.get("plan_sha256"),
            "missing_plans": plan_payload.get("missing_plans", []),
            "entry_count": len(plan_payload.get("entries", [])),
        },
        "matrix": {
            "observed_design_count": matrix_payload.get("observed_design_count"),
            "independent_input_count": matrix_payload.get("independent_input_count"),
            "family_count": matrix_payload.get("family_count"),
            "runtime_fingerprints": matrix_payload.get("runtime_fingerprints", []),
            "candidate_variation": matrix_payload.get("candidate_variation", {}),
        },
        "readiness": {
            "blocking_checks": readiness_payload.get("blocking_checks", []),
            "generalization_status": readiness_payload.get("generalization_status"),
        },
        "effect": {
            "available_pair_count": effect_payload.get("available_pair_count")
            if effect_payload
            else None,
            "improvement_count": (
                effect_payload.get("improvement_count") if effect_payload else None
            ),
        },
        "next_actions": _next_actions(statuses, plan_payload, effect_payload),
        "safe_to_apply": False,
    }
    destination.mkdir(parents=True)
    (destination / "benchmark-summary.json").write_bytes(canonical_bytes(result))
    (destination / "benchmark-summary.md").write_text(_markdown(result), encoding="utf-8")
    return {**result, "output": str(destination)}


def _read(path: str | Path, schema: str) -> dict:
    source = Path(path).expanduser()
    if source.is_dir():
        source /= _SCHEMA_FILES[schema]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExperienceError(
            f"Invalid benchmark artifact: {source}", code="experience_benchmark_invalid"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise ExperienceError(
            f"Invalid benchmark artifact schema: {source}",
            code="experience_benchmark_invalid",
        )
    return payload


def _check_plan(payload: dict) -> None:
    fingerprint = payload.get("plan_sha256")
    if not isinstance(fingerprint, str):
        raise ExperienceError(
            "Benchmark plan has no fingerprint", code="experience_benchmark_invalid"
        )
    unsigned = {key: value for key, value in payload.items() if key != "plan_sha256"}
    if digest(unsigned) != fingerprint:
        raise ExperienceError(
            "Benchmark plan fingerprint is invalid", code="experience_benchmark_invalid"
        )


def _status(statuses: dict[str, str | None]) -> str:
    if any(value == "fail" for value in statuses.values()):
        return "fail"
    if statuses["plan"] == "pending" or statuses["readiness"] == "unknown":
        return "unknown"
    if statuses["effect"] == "unknown":
        return "unknown"
    return "pass"


def _artifact(path: str | Path, payload: dict) -> dict:
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source /= _SCHEMA_FILES[payload["schema"]]
    return {
        "schema": payload["schema"],
        "path": str(source),
        "sha256": _sha256(source),
    }


def _next_actions(statuses: dict[str, str | None], plan: dict, effect: dict | None) -> list[str]:
    actions = []
    if plan.get("missing_plans"):
        actions.append("Create and validate every missing strategy plan before execution")
    if statuses["matrix"] == "fail":
        actions.append("Repair missing or corrupt observations and rerun matrix aggregation")
    if statuses["readiness"] == "unknown":
        actions.append(
            "Collect the missing independent designs, families, candidates, or runtime evidence"
        )
    if effect is None:
        actions.append(
            "Run campaign effect after measured same-design baseline and candidate trials exist"
        )
    elif statuses["effect"] == "unknown":
        actions.append(
            "Keep candidate effect unknown until same-design evidence has valid QoR "
            "and verification"
        )
    if not actions:
        actions.append(
            "Review the measured evidence and publish only through the existing gated release flow"
        )
    return actions


def _markdown(result: dict) -> str:
    lines = [
        "# ECC benchmark summary",
        "",
        f"Status: {result['status']}; exit_code: {result['exit_code']}",
        f"Benchmark: {result['benchmark_id']}; process: {result['process_profile']}",
        "",
        "| Artifact | Status |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {status} |" for name, status in result["statuses"].items())
    lines.extend(["", "## Next actions", ""])
    lines.extend(f"- {item}" for item in result["next_actions"])
    lines.extend(["", "safe_to_apply: false", ""])
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
    except OSError as exc:
        raise ExperienceError(
            f"Benchmark artifact is unreadable: {path}", code="experience_benchmark_invalid"
        ) from exc
    return checksum.hexdigest()
