"""Bounded QoR v3 facts embedded in an Engineering Snapshot."""

from math import isfinite
from typing import Any

QOR_SNAPSHOT_EXTENSION_SCHEMA_VERSION = 1
_MAX_DIAGNOSES = 64
_MAX_INTERVENTIONS = 4
_MAX_ARTIFACT_IDS = 512
_MAX_TEXT = 512


def build_qor_snapshot_extension(analysis: Any, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Project the report into bounded, path-free committed QoR facts."""
    report = analysis.to_dict() if hasattr(analysis, "to_dict") else analysis
    if not isinstance(report, dict):
        raise ValueError("QoR analysis is not an object")

    dimensions = {}
    for key, dimension in report.get("qor_record", {}).items():
        if not isinstance(key, str) or not isinstance(dimension, dict):
            continue
        features = dimension.get("features", [])
        dimensions[key] = {
            "value": _number_or_none(dimension.get("value")),
            "state": _text(dimension.get("state"), "UNKNOWN"),
            "featureIds": [
                feature["feature_id"]
                for feature in features[:32]
                if isinstance(feature, dict) and isinstance(feature.get("feature_id"), str)
            ],
        }

    feasibility = report.get("feasibility")
    feasibility = feasibility if isinstance(feasibility, dict) else {}
    gates = []
    for gate in feasibility.get("gates", []):
        if not isinstance(gate, dict) or not isinstance(gate.get("id"), str):
            continue
        gates.append(
            {
                "id": gate["id"],
                "stage": _text(gate.get("stage")),
                "state": _text(gate.get("state"), "unavailable"),
                "blocksTapeout": bool(gate.get("blocks_tapeout")),
                "metrics": [
                    metric for metric in gate.get("metrics", [])[:32] if isinstance(metric, str)
                ],
                "availability": gate.get("availability")
                if isinstance(gate.get("availability"), str)
                else None,
            }
        )

    summary = report.get("scalar_summary")
    summary = summary if isinstance(summary, dict) else {}
    evidence = report.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    inflation = report.get("inflation")
    inflation = inflation if isinstance(inflation, dict) else {}
    power = report.get("power")
    power = power if isinstance(power, dict) else {}

    return {
        "schemaVersion": QOR_SNAPSHOT_EXTENSION_SCHEMA_VERSION,
        "scoringEngine": "qor-v3",
        "status": "available",
        "score": _number_or_none(summary.get("score")),
        "scalarStatus": _text(summary.get("status"), "NOT_RATED"),
        "profile": _text(summary.get("profile"), "balanced"),
        "qphys": dimensions,
        "feasibility": {
            "status": _text(feasibility.get("status"), "UNKNOWN"),
            "gates": gates[:32],
        },
        "evidence": {
            "index": _number_or_none(evidence.get("index")),
            "state": _text(evidence.get("state"), "NOT_VERIFIED"),
            "integrity": _number_or_none(evidence.get("integrity")),
            "coverage": _number_or_none(evidence.get("coverage")),
            "consistency": _number_or_none(evidence.get("consistency")),
        },
        "diagnoses": [_diagnosis(item) for item in report.get("diagnoses", [])[:_MAX_DIAGNOSES]],
        "inflation": {
            "iPlace": _number_or_none(inflation.get("i_place")),
            "iRoute": _number_or_none(inflation.get("i_route")),
            "iTotal": _number_or_none(inflation.get("i_total")),
            "congestionSeverity": _number_or_none(inflation.get("congestion_severity")),
            "compatibilityStatus": _text(inflation.get("compatibility_status")),
        },
        "power": {
            "totalUw": _number_or_none(power.get("total_uw")),
            "budgetUw": _number_or_none(power.get("budget_uw")),
            "sourceKind": power.get("source_kind")
            if isinstance(power.get("source_kind"), str)
            else None,
            "corner": power.get("corner") if isinstance(power.get("corner"), str) else None,
        },
        "artifactIds": _artifact_ids(artifacts),
    }


def unavailable_qor_snapshot_extension(reason: str) -> dict[str, Any]:
    """Return an explicit unavailable extension without inventing QoR values."""
    return {
        "schemaVersion": QOR_SNAPSHOT_EXTENSION_SCHEMA_VERSION,
        "scoringEngine": "qor-v3",
        "status": "unavailable",
        "reason": _text(reason, "QoR analysis unavailable"),
        "score": None,
        "scalarStatus": "NOT_RATED",
        "profile": "balanced",
        "qphys": {},
        "feasibility": {"status": "UNKNOWN", "gates": []},
        "evidence": {
            "index": None,
            "state": "NOT_VERIFIED",
            "integrity": None,
            "coverage": None,
            "consistency": None,
        },
        "diagnoses": [],
        "inflation": {
            "iPlace": None,
            "iRoute": None,
            "iTotal": None,
            "congestionSeverity": None,
            "compatibilityStatus": "UNAVAILABLE",
        },
        "power": {"totalUw": None, "budgetUw": None, "sourceKind": None, "corner": None},
        "artifactIds": [],
    }


def validate_qor_snapshot_extension(value: object) -> bool:
    """Validate the migration-only extension boundary."""
    if not isinstance(value, dict):
        return False
    return (
        value.get("schemaVersion") == QOR_SNAPSHOT_EXTENSION_SCHEMA_VERSION
        and value.get("scoringEngine") == "qor-v3"
        and value.get("status") in {"available", "unavailable"}
        and isinstance(value.get("qphys"), dict)
        and isinstance(value.get("feasibility"), dict)
        and isinstance(value["feasibility"].get("gates"), list)
        and isinstance(value.get("evidence"), dict)
        and isinstance(value.get("diagnoses"), list)
        and isinstance(value.get("artifactIds"), list)
        and all(isinstance(item, str) and item for item in value["artifactIds"])
    )


def _diagnosis(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"diagnosisId": "unknown", "state": "UNKNOWN", "severity": None}
    interventions = []
    for item in value.get("interventions", [])[:_MAX_INTERVENTIONS]:
        if not isinstance(item, dict):
            continue
        interventions.append(
            {
                "hypothesis": _text(item.get("hypothesis")),
                "tier": _text(item.get("tier")),
                "confidence": _text(item.get("confidence"), "LOW"),
                "parameterKnob": item.get("parameter_knob")
                if isinstance(item.get("parameter_knob"), str)
                else None,
                "validationProcedure": item.get("validation_procedure")
                if isinstance(item.get("validation_procedure"), str)
                else None,
            }
        )
    return {
        "diagnosisId": _text(value.get("diagnosis_id"), "unknown"),
        "state": _text(value.get("state"), "UNKNOWN"),
        "severity": _number_or_none(value.get("severity")),
        "confidence": _text(value.get("diagnosis_confidence"), "LOW"),
        "triggerFeatures": [
            item for item in value.get("trigger_features", [])[:32] if isinstance(item, str)
        ],
        "affectedDimensions": [
            item for item in value.get("affected_dimensions", [])[:16] if isinstance(item, str)
        ],
        "interventions": interventions,
        "interventionConfidence": _text(value.get("intervention_confidence"), "LOW"),
        "validationRequired": value.get("validation_required")
        if isinstance(value.get("validation_required"), str)
        else None,
    }


def _artifact_ids(artifacts: list[dict[str, Any]]) -> list[str]:
    ids = {
        item["artifactId"]
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("artifactId"), str)
    }
    return sorted(ids)[:_MAX_ARTIFACT_IDS]


def _number_or_none(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return value


def _text(value: object, default: str = "") -> str:
    return value[:_MAX_TEXT] if isinstance(value, str) and value else default
