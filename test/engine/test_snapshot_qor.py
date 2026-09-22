from chipcompiler.engine.snapshot_qor import (
    unavailable_qor_snapshot_extension,
    validate_qor_snapshot_extension,
)


def test_qor_extension_validator_accepts_a_valid_diagnosis():
    extension = unavailable_qor_snapshot_extension("analysis unavailable")
    extension["diagnoses"] = [
        {
            "diagnosisId": "diag.test",
            "state": "WATCH",
            "severity": 0.5,
            "confidence": "HIGH",
            "triggerFeatures": [],
            "affectedDimensions": [],
            "interventions": [],
            "interventionConfidence": "LOW",
            "validationRequired": None,
        }
    ]

    assert validate_qor_snapshot_extension(extension)
