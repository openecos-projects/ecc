"""JSON contract for ``home/qor_report.json`` and a structural validator.

The schema mirrors the emitted subset of the spec's Draft 2020-12
contract (§13) restricted to what this engine produces. The validator is
a hand-rolled structural check (no external dependency): it enforces
required keys, enums, and numeric ranges so a malformed report fails
loudly in tests instead of silently downstream.
"""

from chipcompiler.analysis.qor.models import SCHEMA_VERSION

FEASIBILITY_STATUSES = ("PASS", "PHYSICAL_FAIL", "NOT_VERIFIED", "UNKNOWN")
GATE_STATES = ("passed", "failed", "unavailable")
EVIDENCE_STATES = ("HIGH", "MODERATE", "LIMITED", "INSUFFICIENT", "NOT_VERIFIED")
DIMENSION_STATES = ("PASS", "FAIL", "WATCH", "OVER_PROVISIONED", "OPPORTUNITY", "UNKNOWN")
SCALAR_STATUSES = ("GREEN", "YELLOW", "ORANGE", "RED", "FAIL", "NOT_RATED")
TIERS = ("TIER_1_FEASIBILITY", "TIER_2_BOTTLENECK", "TIER_3_OPPORTUNITY")
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")
DIMENSION_KEYS = ("timing", "interconnect", "area", "power", "robustness")

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "EccQorAnalysisReport",
    "type": "object",
    "required": [
        "schema_version",
        "scoring_engine",
        "design",
        "workspace",
        "timestamp",
        "profile",
        "tclk_ns",
        "feasibility",
        "evidence",
        "qor_record",
        "scalar_summary",
        "diagnoses",
        "inflation",
        "flow_steps",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "feasibility": {
            "required": ["status", "gates"],
            "status_enum": FEASIBILITY_STATUSES,
        },
        "evidence": {
            "required": ["index", "state", "integrity", "coverage", "consistency"],
            "state_enum": EVIDENCE_STATES,
            "unit_interval_fields": ["index", "integrity", "coverage", "consistency"],
        },
        "qor_record": {
            "dimension_keys": DIMENSION_KEYS,
            "state_enum": DIMENSION_STATES,
        },
        "scalar_summary": {
            "required": ["score", "status", "profile", "weights"],
            "status_enum": SCALAR_STATUSES,
        },
    },
}


def validate_report(report: dict) -> list:
    """Return a list of structural violations; empty means valid."""
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    if not isinstance(report, dict):
        return ["report is not an object"]
    for key in SCHEMA["required"]:
        require(key in report, f"missing required key {key!r}")
    if errors:
        return errors

    require(report["schema_version"] == SCHEMA_VERSION, "schema_version must be 3")
    require(report["scoring_engine"] == "qor-v3", "scoring_engine must be qor-v3")
    require(isinstance(report["timestamp"], str), "timestamp must be a string")

    feasibility = report["feasibility"]
    require(isinstance(feasibility, dict), "feasibility must be an object")
    require(
        feasibility.get("status") in FEASIBILITY_STATUSES,
        f"feasibility.status invalid: {feasibility.get('status')!r}",
    )
    require(isinstance(feasibility.get("gates"), list), "feasibility.gates must be a list")
    for gate in feasibility["gates"]:
        require(isinstance(gate, dict) and gate.get("id"), "gate requires an id")
        require(gate.get("state") in GATE_STATES, f"gate state invalid: {gate.get('state')!r}")
        require(isinstance(gate.get("blocks_tapeout"), bool), "gate.blocks_tapeout must be bool")

    evidence = report["evidence"]
    require(
        evidence.get("state") in EVIDENCE_STATES,
        f"evidence.state invalid: {evidence.get('state')!r}",
    )
    for field in ("index", "integrity", "coverage", "consistency"):
        value = evidence.get(field)
        limit = 100 if field == "index" else 1
        valid = isinstance(value, (int, float)) and 0 <= value <= limit
        require(value is None or valid, f"evidence.{field} out of range")

    qor_record = report["qor_record"]
    require(isinstance(qor_record, dict), "qor_record must be an object")
    for key in DIMENSION_KEYS:
        dimension = qor_record.get(key)
        require(isinstance(dimension, dict), f"qor_record.{key} missing")
        if isinstance(dimension, dict):
            value = dimension.get("value")
            require(
                value is None or (isinstance(value, (int, float)) and 0 <= value <= 100),
                f"qor_record.{key}.value out of range",
            )
            require(
                dimension.get("state") in DIMENSION_STATES,
                f"qor_record.{key}.state invalid",
            )
            require(
                isinstance(dimension.get("features"), list),
                "dimension.features must be a list",
            )

    summary = report["scalar_summary"]
    require(
        summary.get("status") in SCALAR_STATUSES,
        f"scalar_summary.status invalid: {summary.get('status')!r}",
    )
    score = summary.get("score")
    require(
        score is None or (isinstance(score, (int, float)) and 0 <= score <= 100),
        "scalar_summary.score out of range",
    )
    require(isinstance(summary.get("weights"), dict), "scalar_summary.weights must be an object")

    require(isinstance(report["diagnoses"], list), "diagnoses must be a list")
    for diagnosis in report["diagnoses"]:
        require(
            isinstance(diagnosis, dict) and diagnosis.get("diagnosis_id"),
            "diagnosis requires id",
        )
        severity = diagnosis.get("severity")
        require(
            isinstance(severity, (int, float)) and 0 <= severity <= 1,
            f"diagnosis severity out of range: {severity!r}",
        )
        require(
            diagnosis.get("diagnosis_confidence") in CONFIDENCES,
            "diagnosis_confidence invalid",
        )
        for intervention in diagnosis.get("interventions") or []:
            require(intervention.get("tier") in TIERS, "intervention tier invalid")
            require(
                intervention.get("confidence") in CONFIDENCES,
                "intervention confidence invalid",
            )

    return errors
