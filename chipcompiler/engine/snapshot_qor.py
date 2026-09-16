"""Bounded QoR v3 facts embedded in an Engineering Snapshot."""

from math import isfinite
from typing import Any

from chipcompiler.analysis.qor.schema import (
    CONFIDENCES,
    DIMENSION_KEYS,
    DIMENSION_STATES,
    EVIDENCE_STATES,
    FEASIBILITY_STATUSES,
    GATE_STATES,
    SCALAR_STATUSES,
    TIERS,
)

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
    """Validate the bounded, path-free QoR extension fail-closed."""
    if not isinstance(value, dict):
        return False
    status = value.get("status")
    required = {
        "schemaVersion",
        "scoringEngine",
        "status",
        "score",
        "scalarStatus",
        "profile",
        "qphys",
        "feasibility",
        "evidence",
        "diagnoses",
        "inflation",
        "power",
        "artifactIds",
    }
    if status == "unavailable":
        required.add("reason")
    if (
        set(value) != required
        or value.get("schemaVersion") != QOR_SNAPSHOT_EXTENSION_SCHEMA_VERSION
        or value.get("scoringEngine") != "qor-v3"
        or status not in {"available", "unavailable"}
        or not _bounded_text(
            value.get("profile"),
            values=("balanced", "timing_critical", "low_power", "area_optimized"),
        )
        or not _bounded_number(value.get("score"), 0, 100, nullable=True)
        or value.get("scalarStatus") not in SCALAR_STATUSES
    ):
        return False
    if status == "unavailable" and not _bounded_text(value.get("reason")):
        return False

    qphys = value.get("qphys")
    if not isinstance(qphys, dict) or len(qphys) > len(DIMENSION_KEYS):
        return False
    for key, dimension in qphys.items():
        if key not in DIMENSION_KEYS or not isinstance(dimension, dict):
            return False
        if set(dimension) != {"value", "state", "featureIds"}:
            return False
        if not _bounded_number(dimension["value"], 0, 100, nullable=True):
            return False
        if dimension["state"] not in DIMENSION_STATES or not _bounded_strings(
            dimension["featureIds"], 32
        ):
            return False

    feasibility = value.get("feasibility")
    if not isinstance(feasibility, dict) or set(feasibility) != {"status", "gates"}:
        return False
    if (
        feasibility["status"] not in FEASIBILITY_STATUSES
        or not isinstance(feasibility["gates"], list)
        or len(feasibility["gates"]) > 32
    ):
        return False
    for gate in feasibility["gates"]:
        if not isinstance(gate, dict) or set(gate) != {
            "id",
            "stage",
            "state",
            "blocksTapeout",
            "metrics",
            "availability",
        }:
            return False
        if (
            not _bounded_text(gate["id"])
            or not _bounded_text(gate["stage"])
            or gate["state"] not in GATE_STATES
            or not isinstance(gate["blocksTapeout"], bool)
            or not _bounded_strings(gate["metrics"], 32)
            or not _bounded_text(gate["availability"], nullable=True)
        ):
            return False

    evidence = value.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "index",
        "state",
        "integrity",
        "coverage",
        "consistency",
    }:
        return False
    if (
        evidence["state"] not in EVIDENCE_STATES
        or not _bounded_number(evidence["index"], 0, 100, nullable=True)
        or not all(
            _bounded_number(evidence[field], 0, 1, nullable=True)
            for field in ("integrity", "coverage", "consistency")
        )
    ):
        return False

    diagnoses = value.get("diagnoses")
    if not isinstance(diagnoses, list) or len(diagnoses) > _MAX_DIAGNOSES:
        return False
    for diagnosis in diagnoses:
        if not isinstance(diagnosis, dict) or set(diagnosis) != {
            "diagnosisId",
            "state",
            "severity",
            "confidence",
            "triggerFeatures",
            "affectedDimensions",
            "interventions",
            "interventionConfidence",
            "validationRequired",
        }:
            return False
        if (
            not _bounded_text(diagnosis["diagnosisId"])
            or not _bounded_text(diagnosis["state"])
            or not _bounded_number(diagnosis["severity"], 0, 1)
            or diagnosis["confidence"] not in CONFIDENCES
            or not _bounded_strings(diagnosis["triggerFeatures"], 32)
            or not _bounded_strings(diagnosis["affectedDimensions"], 16)
            or not isinstance(diagnosis["interventions"], list)
            or len(diagnosis["interventions"]) > _MAX_INTERVENTIONS
            or diagnosis["interventionConfidence"] not in CONFIDENCES
            or not _bounded_text(diagnosis["validationRequired"], nullable=True)
        ):
            return False
        for intervention in diagnosis["interventions"]:
            if not isinstance(intervention, dict) or set(intervention) != {
                "hypothesis",
                "tier",
                "confidence",
                "parameterKnob",
                "validationProcedure",
            }:
                return False
            if (
                not _bounded_text(intervention["hypothesis"])
                or intervention["tier"] not in TIERS
                or intervention["confidence"] not in CONFIDENCES
                or not _bounded_text(intervention["parameterKnob"], nullable=True)
                or not _bounded_text(intervention["validationProcedure"], nullable=True)
            ):
                return False

    inflation = value.get("inflation")
    if not isinstance(inflation, dict) or set(inflation) != {
        "iPlace",
        "iRoute",
        "iTotal",
        "congestionSeverity",
        "compatibilityStatus",
    }:
        return False
    if not all(
        _bounded_number(inflation[field], 0, None, nullable=True)
        for field in ("iPlace", "iRoute", "iTotal", "congestionSeverity")
    ) or inflation["compatibilityStatus"] not in {
        "EXACT_COMPATIBLE",
        "MAPPED_COMPATIBLE",
        "INCOMPATIBLE",
        "UNAVAILABLE",
    }:
        return False

    power = value.get("power")
    if not isinstance(power, dict) or set(power) != {"totalUw", "budgetUw", "sourceKind", "corner"}:
        return False
    if (
        not _bounded_number(power["totalUw"], 0, None, nullable=True)
        or not _bounded_number(power["budgetUw"], 0, None, nullable=True)
        or power["sourceKind"] not in {None, "signoff", "synthesis"}
        or not _bounded_text(power["corner"], nullable=True)
    ):
        return False

    return _bounded_strings(value["artifactIds"], _MAX_ARTIFACT_IDS)


def _bounded_number(
    value: object, low: float | None, high: float | None, *, nullable: bool
) -> bool:
    if value is None:
        return nullable
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def _bounded_text(
    value: object, *, nullable: bool = False, values: tuple[str, ...] | None = None
) -> bool:
    if value is None:
        return nullable
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= _MAX_TEXT
        and (values is None or value in values)
    )


def _bounded_strings(value: object, maximum: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= maximum
        and all(_bounded_text(item) for item in value)
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
