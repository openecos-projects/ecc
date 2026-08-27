"""ECC-side producer for the hash-bound parameter application receipt.

This module deliberately has no dependency on ``ecos_agent``.  Tool adapters
pass structured consumer facts; this producer only assembles and persists the
frozen JSON envelope.
"""

from __future__ import annotations

import hashlib
import json
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
    activation = runtime_report.get("activation")
    if not isinstance(activation, Mapping):
        raise ValueError("native activation facts are required")
    if activation.get("status") == "used" and not activation.get("consumers"):
        raise ValueError("used activation requires consumer evidence")
    normalized_tool = dict(tool)
    normalized_tool.setdefault("source_sha256", None)
    normalized_materialization = dict(materialization)
    normalized_materialization.setdefault("parent_ref", None)
    payload: dict[str, Any] = {
        "schema_version": "tool.parameter_application_receipt.v1",
        "receipt_id": receipt_id,
        "tool": normalized_tool,
        "context": dict(context),
        "requested": dict(requested),
        "materialization": normalized_materialization,
        "effective_initial": runtime_report.get(
            "effective_initial", {"value": None, "unit": requested.get("unit", "")}
        ),
        "transitions": list(runtime_report.get("transitions", [])),
        "application_status": runtime_report.get("application_status", "unknown"),
        "activation": dict(activation),
        "effective_final": runtime_report.get(
            "effective_final", {"value": None, "unit": requested.get("unit", "")}
        ),
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
