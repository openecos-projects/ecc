"""JSON contract for ``home/qor_report.json`` and a structural validator.

The schema mirrors the emitted subset of the spec's Draft 2020-12
contract (§13) restricted to what this engine produces. The validator is
a hand-rolled structural check (no external dependency): it enforces
required keys, enums, and numeric ranges so a malformed report fails
loudly in tests instead of silently downstream.
"""

from math import isfinite

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

    def finite_number(value, *, low=None, high=None, nullable=False):
        if value is None and nullable:
            return True
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            return False
        return (low is None or value >= low) and (high is None or value <= high)

    def string_list(value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    require(report["schema_version"] == SCHEMA_VERSION, "schema_version must be 3")
    require(report["scoring_engine"] == "qor-v3", "scoring_engine must be qor-v3")
    for field in ("design", "workspace", "timestamp", "profile"):
        require(isinstance(report[field], str), f"{field} must be a string")
    require(finite_number(report["tclk_ns"], low=0, nullable=True), "tclk_ns invalid")

    feasibility = report["feasibility"]
    require(isinstance(feasibility, dict), "feasibility must be an object")
    if isinstance(feasibility, dict):
        require(feasibility.get("status") in FEASIBILITY_STATUSES, "feasibility.status invalid")
        gates = feasibility.get("gates")
        require(isinstance(gates, list), "feasibility.gates must be a list")
        if isinstance(gates, list):
            for gate in gates:
                valid_gate = isinstance(gate, dict)
                require(
                    valid_gate and isinstance(gate.get("id"), str) and gate["id"],
                    "gate requires an id",
                )
                if not valid_gate:
                    continue
                require(gate.get("state") in GATE_STATES, "gate state invalid")
                require(isinstance(gate.get("stage"), str), "gate.stage must be a string")
                require(isinstance(gate.get("predicate"), str), "gate.predicate must be a string")
                require(
                    isinstance(gate.get("blocks_tapeout"), bool), "gate.blocks_tapeout must be bool"
                )
                require(string_list(gate.get("metrics")), "gate.metrics must be a string list")
                require(
                    gate.get("availability") is None or isinstance(gate.get("availability"), str),
                    "gate.availability invalid",
                )
                timing = gate.get("timing_slack")
                if timing is not None:
                    valid_timing = isinstance(timing, dict)
                    require(valid_timing, "gate.timing_slack must be an object or null")
                    if valid_timing:
                        for field in ("ws_ns", "wns_ns", "tns_ns"):
                            require(
                                finite_number(timing.get(field), nullable=True),
                                f"timing_slack.{field} invalid",
                            )
                        require(
                            finite_number(timing.get("nvp"), low=0, nullable=True),
                            "timing_slack.nvp invalid",
                        )
                        require(
                            timing.get("worst_corner") is None
                            or isinstance(timing.get("worst_corner"), str),
                            "timing_slack.worst_corner invalid",
                        )

    evidence = report["evidence"]
    require(isinstance(evidence, dict), "evidence must be an object")
    if isinstance(evidence, dict):
        require(evidence.get("state") in EVIDENCE_STATES, "evidence.state invalid")
        require(
            finite_number(evidence.get("index"), low=0, high=100, nullable=True),
            "evidence.index out of range",
        )
        for field in ("integrity", "coverage", "consistency"):
            require(
                finite_number(evidence.get(field), low=0, high=1, nullable=True),
                f"evidence.{field} out of range",
            )

    qor_record = report["qor_record"]
    require(isinstance(qor_record, dict), "qor_record must be an object")
    if isinstance(qor_record, dict):
        for key in DIMENSION_KEYS:
            dimension = qor_record.get(key)
            valid_dimension = isinstance(dimension, dict)
            require(valid_dimension, f"qor_record.{key} missing")
            if not valid_dimension:
                continue
            require(dimension.get("key") == key, f"qor_record.{key}.key mismatch")
            require(
                finite_number(dimension.get("value"), low=0, high=100, nullable=True),
                f"qor_record.{key}.value invalid",
            )
            require(dimension.get("state") in DIMENSION_STATES, f"qor_record.{key}.state invalid")
            features = dimension.get("features")
            require(isinstance(features, list), f"qor_record.{key}.features must be a list")
            if isinstance(features, list):
                for feature in features:
                    valid_feature = isinstance(feature, dict)
                    require(valid_feature, "feature must be an object")
                    if not valid_feature:
                        continue
                    for field in (
                        "feature_id",
                        "unit",
                        "formula",
                        "classification",
                        "semantic_class",
                    ):
                        require(
                            isinstance(feature.get(field), str), f"feature.{field} must be a string"
                        )
                    require(
                        finite_number(feature.get("value"), nullable=True), "feature.value invalid"
                    )
                    require(
                        feature.get("state")
                        in ("PASS", "FAIL", "WATCH", "OPPORTUNITY", "UNKNOWN", "NOT_APPLICABLE"),
                        "feature.state invalid",
                    )
                    require(
                        string_list(feature.get("input_metric_ids")),
                        "feature.input_metric_ids invalid",
                    )
                    require(
                        isinstance(feature.get("input_source_artifacts"), list),
                        "feature.input_source_artifacts invalid",
                    )

    summary = report["scalar_summary"]
    require(isinstance(summary, dict), "scalar_summary must be an object")
    if isinstance(summary, dict):
        require(summary.get("status") in SCALAR_STATUSES, "scalar_summary.status invalid")
        require(
            finite_number(summary.get("score"), low=0, high=100, nullable=True),
            "scalar_summary.score out of range",
        )
        require(isinstance(summary.get("profile"), str), "scalar_summary.profile must be a string")
        require(
            isinstance(summary.get("weights"), dict), "scalar_summary.weights must be an object"
        )

    diagnoses = report["diagnoses"]
    require(isinstance(diagnoses, list), "diagnoses must be a list")
    if isinstance(diagnoses, list):
        for diagnosis in diagnoses:
            valid_diagnosis = isinstance(diagnosis, dict)
            require(
                valid_diagnosis
                and isinstance(diagnosis.get("diagnosis_id"), str)
                and diagnosis["diagnosis_id"],
                "diagnosis requires id",
            )
            if not valid_diagnosis:
                continue
            require(isinstance(diagnosis.get("state"), str), "diagnosis.state invalid")
            require(
                finite_number(diagnosis.get("severity"), low=0, high=1),
                "diagnosis severity invalid",
            )
            require(
                diagnosis.get("diagnosis_confidence") in CONFIDENCES, "diagnosis_confidence invalid"
            )
            require(
                string_list(diagnosis.get("trigger_features")), "diagnosis.trigger_features invalid"
            )
            require(
                string_list(diagnosis.get("affected_dimensions")),
                "diagnosis.affected_dimensions invalid",
            )
            require(
                isinstance(diagnosis.get("interpretation"), str), "diagnosis.interpretation invalid"
            )
            interventions = diagnosis.get("interventions")
            require(isinstance(interventions, list), "diagnosis.interventions must be a list")
            if isinstance(interventions, list):
                for intervention in interventions:
                    valid_intervention = isinstance(intervention, dict)
                    require(valid_intervention, "intervention must be an object")
                    if valid_intervention:
                        require(
                            isinstance(intervention.get("hypothesis"), str),
                            "intervention.hypothesis invalid",
                        )
                        require(intervention.get("tier") in TIERS, "intervention tier invalid")
                        require(
                            intervention.get("confidence") in CONFIDENCES,
                            "intervention confidence invalid",
                        )

    inflation = report["inflation"]
    require(isinstance(inflation, dict), "inflation must be an object")
    if isinstance(inflation, dict):
        for field in ("i_place", "i_route", "i_total", "congestion_severity"):
            require(
                finite_number(inflation.get(field), low=0, nullable=True),
                f"inflation.{field} invalid",
            )
        require(
            inflation.get("compatibility_status")
            in ("EXACT_COMPATIBLE", "MAPPED_COMPATIBLE", "INCOMPATIBLE"),
            "inflation.compatibility_status invalid",
        )
    require(isinstance(report["flow_steps"], dict), "flow_steps must be an object")
    require(string_list(report.get("config_warnings", [])), "config_warnings must be a string list")

    return errors
