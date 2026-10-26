"""Validate tool-observed parameter application receipts without trusting config."""

from __future__ import annotations

import hashlib
import json
import math
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ecc_experience.files import read_json
from ecc_experience.models import ExperienceError

MAX_RECEIPTS = 256
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
_KNOBS = {
    "target_density",
    "target_overflow",
    "cell_padding_x",
    "routability_opt",
    "density_weight",
    "core_util",
    "aspect_ratio",
}


@dataclass
class ReceiptResult:
    evidence: dict
    files: list[Path] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def capture_parameter_evidence(
    workspace: str | Path,
    facts: dict,
    *,
    attempt_id: str | None = None,
) -> ReceiptResult:
    root = Path(workspace).expanduser().resolve()
    specification = facts.get("workspaceSpec", {})
    configured = specification.get("parameters", {}) if isinstance(specification, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    receipts = _receipt_paths(root)
    if not receipts:
        return ReceiptResult(
            evidence={
                "level": "configured" if configured else "unknown",
                "receipt_sha256": None,
                "receipt_status": "not_applicable" if not configured else "missing",
                "applied_parameters": [],
                "limitations": [
                    "Configured parameters do not prove tool consumption"
                    if configured
                    else "No configured parameters or application receipt were observed"
                ],
            },
            limitations=[],
        )

    files: list[Path] = []
    limitations: list[str] = []
    applied: list[dict] = []
    receipt_hashes: list[str] = []
    invalid = False
    stages = {
        str(step.get("name", "")).casefold()
        for step in facts.get("flow", {}).get("steps", [])
        if isinstance(step, dict)
    }
    selected = receipts
    if attempt_id is not None:
        bound = []
        for path in receipts:
            try:
                payload = read_json(path, MAX_RECEIPT_BYTES)
            except ExperienceError:
                continue
            context = payload.get("context")
            if isinstance(context, dict) and context.get("run_id") == attempt_id:
                bound.append(path)
        if bound:
            selected = bound
    for path in selected[:MAX_RECEIPTS]:
        try:
            payload = read_json(path, MAX_RECEIPT_BYTES)
            record, related = _validate_receipt(path, payload, configured=configured, stages=stages)
        except (ExperienceError, OSError, ValueError, TypeError, KeyError) as exc:
            invalid = True
            limitations.append(f"invalid_parameter_receipt:{path.name}:{_short(exc)}")
            files.append(path)
            continue
        files.append(path)
        files.extend(related)
        receipt_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        limitations.extend(record["limitations"])
        if record["status"] == "effective":
            applied.append(
                {
                    "knob_id": record["knob_id"],
                    "value": record["value"],
                    "actual_value": record["actual_value"],
                    "unit": record["unit"],
                    "status": "effective",
                    "candidate_id": record["candidate_id"],
                    "stage": record["stage"],
                }
            )
        elif record["status"] == "inactive":
            reason = record.get("reason") or "unknown"
            limitations.append(f"parameter_receipt_inactive:{record['knob_id']}:{reason}")

    conflicts = _conflicts(applied)
    if conflicts:
        limitations.extend(f"parameter_receipt_conflict:{item}" for item in conflicts)
        invalid = True
    if invalid:
        level = "unknown"
        receipt_status = "invalid"
    elif applied:
        level = "applied"
        receipt_status = "valid"
    else:
        level = "configured" if configured else "unknown"
        receipt_status = "valid"
        limitations.append("Parameter receipts did not prove effective tool consumption")
    return ReceiptResult(
        evidence={
            "level": level,
            "receipt_sha256": (
                hashlib.sha256("\n".join(sorted(receipt_hashes)).encode()).hexdigest()
                if receipt_hashes
                else None
            ),
            "receipt_status": receipt_status,
            "applied_parameters": applied if not invalid else [],
            "limitations": sorted(set(limitations)),
        },
        files=_unique(files),
        limitations=sorted(set(limitations)),
    )


def _receipt_paths(root: Path) -> list[Path]:
    candidates = [root / "analysis/parameter_application_receipt.v2.json"]
    candidate_root = root / ".agent/candidates"
    if candidate_root.is_dir() and not candidate_root.is_symlink():
        with suppress(OSError):
            candidates.extend(
                sorted(
                    (
                        path
                        for path in candidate_root.glob(
                            "*/analysis/parameter_application_receipt.v2.json"
                        )
                        if path.is_file() and not path.is_symlink()
                    ),
                    key=lambda path: (path.stat().st_mtime_ns, str(path)),
                    reverse=True,
                )[:MAX_RECEIPTS]
            )
    return _unique([path for path in candidates if path.is_file() and not path.is_symlink()])


def _validate_receipt(
    path: Path, payload: dict, *, configured: dict, stages: set[str]
) -> tuple[dict, list[Path]]:
    if payload.get("schema_version") != "tool.parameter_application_receipt.v2":
        raise ValueError("unsupported receipt schema")
    if not isinstance(payload.get("receipt_id"), str) or not payload["receipt_id"]:
        raise ValueError("receipt ID is invalid")
    evidence_sha = payload.get("evidence_sha256")
    if not isinstance(evidence_sha, str) or not evidence_sha.startswith("sha256:"):
        raise ValueError("receipt evidence hash is invalid")
    if evidence_sha != _canonical_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    ):
        raise ValueError("receipt evidence hash does not match content")
    context = payload.get("context")
    requested = payload.get("requested")
    materialization = payload.get("materialization")
    if not all(isinstance(value, dict) for value in (context, requested, materialization)):
        raise ValueError("receipt sections are missing")
    knob = requested.get("knob_id")
    if knob not in _KNOBS:
        raise ValueError("receipt knob is unsupported")
    value = requested.get("value")
    unit = requested.get("unit")
    status = payload.get("status")
    if status not in {"effective", "inactive", "unknown"} or not isinstance(unit, str) or not unit:
        raise ValueError("receipt status or unit is invalid")
    actual = payload.get("actual_value")
    if status == "effective" and actual is None:
        raise ValueError("effective receipt has no actual value")
    if status == "unknown" and actual is not None:
        raise ValueError("unknown receipt must not claim an actual value")
    stage = context.get("stage")
    if not isinstance(stage, str) or not stage or stage.casefold() not in stages:
        raise ValueError("receipt stage is absent from the committed flow")
    configured_value = _configured_value(configured, knob)
    if configured_value is None or not _same_value(configured_value, value):
        raise ValueError("receipt request is not present in the committed configuration")

    candidate_id = materialization.get("candidate_id")
    target_step = materialization.get("target_step")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("materialization candidate is invalid")
    if not isinstance(target_step, str) or target_step.casefold() != stage.casefold():
        raise ValueError("materialization target step differs from receipt context")
    receipt_dir = path.parent
    candidate_root = receipt_dir.parent
    if candidate_root.name != candidate_id:
        raise ValueError("receipt path is not bound to its candidate")
    related: list[Path] = []
    materialization_ref = materialization.get("receipt_ref")
    if not isinstance(materialization_ref, str) or not materialization_ref:
        raise ValueError("materialization receipt reference is missing")
    materialization_path = _safe_relative(candidate_root, materialization_ref)
    related.append(materialization_path)
    materialization_payload = read_json(materialization_path, MAX_RECEIPT_BYTES)
    materialization_sha = materialization.get("receipt_sha256")
    if not isinstance(materialization_sha, str) or materialization_sha != _canonical_sha256(
        {key: item for key, item in materialization_payload.items() if key != "receipt_sha256"}
    ):
        raise ValueError("materialization receipt hash does not match")
    if (
        materialization_payload.get("schema") != "ecc.workspace.candidate_materialization.v1"
        or materialization_payload.get("candidate_id") != candidate_id
        or str(materialization_payload.get("target_step", "")).casefold() != stage.casefold()
    ):
        raise ValueError("materialization receipt identity is invalid")
    written_value = materialization.get("written_value")
    patch = materialization_payload.get("patch")
    if not isinstance(patch, list) or not patch or not isinstance(patch[0], dict):
        raise ValueError("materialization patch is invalid")
    if patch[0].get("knob_id") != knob or not _same_value(patch[0].get("value"), written_value):
        raise ValueError("materialization patch differs from the receipt")
    patch_sha = materialization.get("patch_sha256")
    if patch_sha != _canonical_sha256(patch):
        raise ValueError("materialization patch hash does not match")
    _validate_file_binding(candidate_root, materialization, "config_ref", "config_after_sha256")
    if materialization.get("config_ref"):
        related.append(_safe_relative(candidate_root, materialization["config_ref"]))
    _validate_file_binding(
        candidate_root,
        materialization,
        "after_snapshot_ref",
        "after_snapshot_sha256",
    )
    if materialization.get("after_snapshot_ref"):
        related.append(_safe_relative(candidate_root, materialization["after_snapshot_ref"]))
    return (
        {
            "knob_id": knob,
            "value": value,
            "actual_value": actual,
            "unit": unit,
            "status": status,
            "candidate_id": candidate_id,
            "stage": stage,
            "reason": payload.get("reason") if isinstance(payload.get("reason"), str) else None,
            "limitations": [
                "Parameter receipt proves materialization and declared tool consumption, "
                "not QoR improvement"
            ],
        },
        related,
    )


def _configured_value(configured: dict, knob: str) -> Any | None:
    for key, value in configured.items():
        if isinstance(key, str) and (key == knob or key.endswith(f".{knob}")):
            return value
    return None


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return (
            math.isfinite(left)
            and math.isfinite(right)
            and math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
        )
    return left == right


def _validate_file_binding(
    root: Path, materialization: dict, reference_key: str, hash_key: str
) -> None:
    reference = materialization.get(reference_key)
    expected = materialization.get(hash_key)
    if not isinstance(reference, str) or not isinstance(expected, str):
        raise ValueError(f"materialization {reference_key} is missing")
    path = _safe_relative(root, reference)
    checksum, _size = _file_sha256(path)
    if checksum != expected:
        raise ValueError(f"materialization {reference_key} hash does not match")


def _safe_relative(root: Path, reference: str) -> Path:
    relative = Path(reference)
    if not reference or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("materialization reference is unsafe")
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError("materialization file is unavailable")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("materialization file escapes candidate root")
    return resolved


def _file_sha256(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while content := stream.read(1024 * 1024):
            checksum.update(content)
            size += len(content)
    return "sha256:" + checksum.hexdigest(), size


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _conflicts(applied: list[dict]) -> list[str]:
    values: dict[str, list[Any]] = {}
    for item in applied:
        values.setdefault(item["knob_id"], []).append(item["value"])
    conflicts = []
    for knob, observed in values.items():
        if any(not _same_value(observed[0], item) for item in observed[1:]):
            conflicts.append(knob)
    return sorted(conflicts)


def _unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _short(exc: Exception) -> str:
    return (str(exc) or type(exc).__name__)[:200]
