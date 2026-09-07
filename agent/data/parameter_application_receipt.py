"""ECC-side producer for the hash-bound parameter application receipt.

This module deliberately has no dependency on ``ecos_agent``.  Tool adapters
pass structured consumer facts; this producer only assembles and persists the
frozen JSON envelope.
"""

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _sha256(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_parameter_application_receipt(
    *,
    receipt_id: str,
    tool: Mapping[str, Any],
    context: Mapping[str, Any],
    requested: Mapping[str, Any],
    materialization: Mapping[str, Any],
    runtime_report: Mapping[str, Any],
    destination: Path | None = None,
) -> dict[str, Any]:
    """Aggregate native runtime facts and optionally atomically write the receipt."""
    if not receipt_id or not requested.get("knob_id"):
        raise ValueError("receipt identity is required")
    normalized_tool = dict(tool)
    required_tool = ("name", "revision", "source_sha256")
    if any(
        not isinstance(normalized_tool.get(key), str) or not normalized_tool[key].strip()
        for key in required_tool
    ):
        raise ValueError("complete tool metadata is required")
    if normalized_tool["revision"] == "bound":
        raise ValueError("bound tool metadata is not allowed")
    if not _is_sha256(normalized_tool["source_sha256"]):
        raise ValueError("tool source_sha256 is invalid")
    if runtime_report.get("schema_version") != "tool.parameter_runtime_report.v2":
        raise ValueError("runtime report v2 is required")
    status = runtime_report.get("status")
    actual = runtime_report.get("actual_value")
    if status not in {"effective", "inactive", "unknown"}:
        raise ValueError("parameter status is invalid")
    if actual is not None and (
        type(actual) not in {bool, int, float}
        or (type(actual) is float and not math.isfinite(actual))
    ):
        raise ValueError("actual parameter value is invalid")
    if status == "effective" and actual is None:
        raise ValueError("effective parameter requires an actual value")
    reason = runtime_report.get("reason")
    observation = runtime_report.get("observation")
    if (reason is not None and not isinstance(reason, str)) or not isinstance(observation, dict):
        raise ValueError("parameter observation is invalid")
    normalized_materialization = dict(materialization)
    normalized_materialization.setdefault("parent_ref", None)
    payload: dict[str, Any] = {
        "schema_version": "tool.parameter_application_receipt.v2",
        "receipt_id": receipt_id,
        "tool": normalized_tool,
        "context": dict(context),
        "requested": dict(requested),
        "materialization": normalized_materialization,
        "actual_value": actual,
        "status": status,
        "reason": reason,
        "observation": observation,
    }
    payload["evidence_sha256"] = _sha256(payload)
    if destination is not None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(temporary, destination)
    return payload


def _is_sha256(value: str) -> bool:
    digest = value.removeprefix("sha256:")
    return (
        value.startswith("sha256:")
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )
