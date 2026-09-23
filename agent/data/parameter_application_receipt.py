"""ECC-side producer for the hash-bound parameter application receipt."""

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_RUNTIME_SCHEMA = "tool.parameter_runtime_report.v3"
_RECEIPT_SCHEMA = "tool.parameter_application_receipt.v3"
_APPLICATION_STATUSES = {"applied", "inactive", "failed", "unknown"}
_VALUE_RELATIONS = {
    "exact",
    "converted",
    "quantized",
    "clamped",
    "floored",
    "transformed",
    "rederived",
    "unknown",
}


def _sha256(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _valid_value(value: Any) -> bool:
    return type(value) in {bool, int, float} and not (
        type(value) is float and not math.isfinite(value)
    )


def _value_record(value: Any, unit: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not _valid_value(value) or not isinstance(unit, str) or not unit.strip():
        raise ValueError("parameter value record is invalid")
    return {"value": value, "unit": unit}


def _validate_observed_record(record: Any, name: str) -> dict[str, Any] | None:
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise ValueError(f"{name} record is invalid")
    normalized = dict(record)
    value = normalized.get("value")
    unit = normalized.get("unit")
    source = normalized.get("source")
    if not _valid_value(value) or not isinstance(unit, str) or not unit.strip():
        raise ValueError(f"{name} record is invalid")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{name} source is invalid")
    return {"value": value, "unit": unit, "source": source}


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
    if runtime_report.get("schema_version") != _RUNTIME_SCHEMA:
        raise ValueError("runtime report v3 is required")

    runtime_parameter = runtime_report.get("parameter")
    if not isinstance(runtime_parameter, Mapping):
        raise ValueError("runtime parameter record is invalid")
    knob_id = requested.get("knob_id")
    if runtime_parameter.get("knob_id") != knob_id:
        raise ValueError("runtime parameter binding is invalid")
    requested_value = requested.get("value")
    requested_unit = requested.get("unit")
    if not _valid_value(requested_value) or not isinstance(requested_unit, str) or not requested_unit.strip():
        raise ValueError("requested parameter value is invalid")

    materialized_value = materialization.get("written_value")
    materialized_unit = materialization.get("unit")
    runtime_written = runtime_parameter.get("written")
    if (
        not isinstance(runtime_written, Mapping)
        or runtime_written.get("value") != materialized_value
        or runtime_written.get("unit") != materialized_unit
    ):
        raise ValueError("runtime written value does not match materialization")
    written = _value_record(materialized_value, materialized_unit)
    if written is None:
        raise ValueError("materialized parameter value is required")

    application = runtime_report.get("application")
    if not isinstance(application, Mapping):
        raise ValueError("parameter application is invalid")
    application = dict(application)
    if application.get("status") not in _APPLICATION_STATUSES:
        raise ValueError("parameter application status is invalid")
    if application.get("relation") not in _VALUE_RELATIONS:
        raise ValueError("parameter value relation is invalid")
    reason = application.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("parameter application reason is invalid")
    observation = runtime_report.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("parameter observation is invalid")

    parameter = {
        "knob_id": knob_id,
        "requested": _value_record(requested_value, requested_unit),
        "written": written,
        "consumed": _validate_observed_record(runtime_parameter.get("consumed"), "consumed"),
        "realized": _validate_observed_record(runtime_parameter.get("realized"), "realized"),
    }
    normalized_materialization = dict(materialization)
    normalized_materialization.setdefault("parent_ref", None)
    payload: dict[str, Any] = {
        "schema_version": _RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "tool": normalized_tool,
        "context": dict(context),
        "parameter": parameter,
        "materialization": normalized_materialization,
        "application": application,
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
