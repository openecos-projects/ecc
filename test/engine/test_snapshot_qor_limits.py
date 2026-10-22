"""Each bounded QoR field has its own limit: exactly the limit passes, +1 fails."""

from chipcompiler.analysis.qor.schema import (
    CONFIDENCES,
    DIMENSION_KEYS,
    DIMENSION_STATES,
    EVIDENCE_STATES,
    FEASIBILITY_STATUSES,
    GATE_STATES,
    SCALAR_STATUSES,
)
from chipcompiler.engine.snapshot_qor import (
    _MAX_DIMENSION_FEATURE_IDS,
    _MAX_FEASIBILITY_GATES,
    _MAX_GATE_METRICS,
    _MAX_TRIGGER_FEATURES,
    build_qor_snapshot_extension,
    validate_qor_snapshot_extension,
)


def _gate(metrics=None) -> dict:
    return {
        "id": "gate",
        "stage": "stage",
        "state": next(iter(GATE_STATES)),
        "blocksTapeout": False,
        "metrics": metrics or [],
        "availability": None,
    }


def _diagnosis(trigger_features=None) -> dict:
    return {
        "diagnosisId": "diagnosis",
        "state": "OPEN",
        "severity": 0.5,
        "confidence": next(iter(CONFIDENCES)),
        "triggerFeatures": trigger_features or [],
        "affectedDimensions": [],
        "interventions": [],
        "interventionConfidence": next(iter(CONFIDENCES)),
        "validationRequired": None,
    }


def _valid_extension() -> dict:
    report = {
        "scalar_summary": {
            "status": next(iter(SCALAR_STATUSES)),
            "score": 50.0,
            "profile": "balanced",
        },
        "qor_record": {
            key: {"value": 50.0, "state": next(iter(DIMENSION_STATES)), "features": []}
            for key in DIMENSION_KEYS
        },
        "evidence": {
            "index": 0.5,
            "state": next(iter(EVIDENCE_STATES)),
            "integrity": 0.5,
            "coverage": 0.5,
            "consistency": 0.5,
        },
        "inflation": {
            "i_place": 0.1,
            "i_route": 0.1,
            "i_total": 0.2,
            "congestion_severity": 0.1,
            "compatibility_status": "EXACT_COMPATIBLE",
        },
        "power": {
            "total_uw": 1.0,
            "budget_uw": 1.0,
            "source_kind": "signoff",
            "corner": "typical",
        },
        "feasibility": {
            "status": next(iter(FEASIBILITY_STATUSES)),
            "gates": [_gate()],
        },
        "diagnoses": [_diagnosis()],
    }
    extension = build_qor_snapshot_extension(report, [])
    assert validate_qor_snapshot_extension(extension)
    return extension


def test_dimension_feature_ids_limit():
    extension = _valid_extension()
    dimension = next(iter(extension["qphys"].values()))
    dimension["featureIds"] = ["f"] * _MAX_DIMENSION_FEATURE_IDS
    assert validate_qor_snapshot_extension(extension)

    dimension["featureIds"] = ["f"] * (_MAX_DIMENSION_FEATURE_IDS + 1)
    assert not validate_qor_snapshot_extension(extension)


def test_feasibility_gates_limit():
    extension = _valid_extension()
    extension["feasibility"]["gates"] = [_gate()] * _MAX_FEASIBILITY_GATES
    assert validate_qor_snapshot_extension(extension)

    extension["feasibility"]["gates"] = [_gate()] * (_MAX_FEASIBILITY_GATES + 1)
    assert not validate_qor_snapshot_extension(extension)


def test_gate_metrics_limit():
    extension = _valid_extension()
    extension["feasibility"]["gates"] = [_gate(["m"] * _MAX_GATE_METRICS)]
    assert validate_qor_snapshot_extension(extension)

    extension["feasibility"]["gates"] = [_gate(["m"] * (_MAX_GATE_METRICS + 1))]
    assert not validate_qor_snapshot_extension(extension)


def test_trigger_features_limit():
    extension = _valid_extension()
    extension["diagnoses"] = [_diagnosis(["t"] * _MAX_TRIGGER_FEATURES)]
    assert validate_qor_snapshot_extension(extension)

    extension["diagnoses"] = [_diagnosis(["t"] * (_MAX_TRIGGER_FEATURES + 1))]
    assert not validate_qor_snapshot_extension(extension)
