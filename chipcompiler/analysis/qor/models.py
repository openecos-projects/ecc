"""Typed records for the ECC-QoR draft 3 analysis report.

Physical design quality (``Qphys``), physical signoff feasibility, and
measurement evidence completeness are three distinct semantic domains;
their records are never merged. Every score coordinate is ``[0, 100] or
None`` — a dimension that cannot be evaluated is ``None`` with an
explicit ``UNKNOWN`` state, never zero.
"""

import dataclasses

SCHEMA_VERSION = 3
SCORING_ENGINE = "qor-v3"


def to_dict(value):
    """Convert nested dataclasses/lists/dicts into JSON-safe structures."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_dict(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_dict(item) for key, item in value.items()}
    return value


@dataclasses.dataclass(frozen=True)
class SourceArtifact:
    metric: str
    path: str
    selector: str


@dataclasses.dataclass(frozen=True)
class FeatureRecord:
    feature_id: str
    value: float | None
    unit: str
    formula: str
    classification: str
    semantic_class: str
    state: str
    input_metric_ids: list
    input_source_artifacts: list
    interpretation: str = ""
    compatibility: dict | None = None


@dataclasses.dataclass(frozen=True)
class QorDimension:
    key: str
    value: float | None
    state: str
    features: list


@dataclasses.dataclass(frozen=True)
class SlackView:
    ws_ns: float | None
    wns_ns: float | None
    tns_ns: float | None = None
    nvp: int | None = None
    worst_corner: str | None = None


@dataclasses.dataclass(frozen=True)
class FeasibilityGate:
    id: str
    stage: str
    state: str  # passed | failed | unavailable
    predicate: str
    blocks_tapeout: bool
    metrics: list
    # Why an unavailable gate could not be evaluated: the stage never
    # completed ("not_verified") or it completed with missing/corrupt
    # evidence ("corrupt"). None when state is not "unavailable".
    availability: str | None = None
    timing_slack: SlackView | None = None


@dataclasses.dataclass(frozen=True)
class Feasibility:
    status: str  # PASS | PHYSICAL_FAIL | NOT_VERIFIED | UNKNOWN
    gates: list


@dataclasses.dataclass(frozen=True)
class Evidence:
    index: float | None
    state: str  # HIGH | MODERATE | LIMITED | INSUFFICIENT | NOT_VERIFIED
    integrity: float | None
    coverage: float | None
    consistency: float | None


@dataclasses.dataclass(frozen=True)
class Intervention:
    hypothesis: str
    tier: str  # TIER_1_FEASIBILITY | TIER_2_BOTTLENECK | TIER_3_OPPORTUNITY
    confidence: str  # HIGH | MEDIUM | LOW
    parameter_knob: str | None = None
    validation_procedure: str | None = None


@dataclasses.dataclass(frozen=True)
class SupportingMetric:
    name: str
    value: object  # number or string
    unit: str
    source: str


@dataclasses.dataclass(frozen=True)
class Diagnosis:
    diagnosis_id: str
    state: str
    severity: float
    diagnosis_confidence: str
    trigger_features: list
    supporting_metrics: list
    interpretation: str
    affected_dimensions: list
    interventions: list
    intervention_confidence: str
    validation_required: str | None = None


@dataclasses.dataclass(frozen=True)
class ScalarSummary:
    score: float | None
    status: str  # GREEN | YELLOW | ORANGE | RED | FAIL | NOT_RATED
    profile: str
    weights: dict


@dataclasses.dataclass(frozen=True)
class InflationView:
    """Tri-partite interconnect decomposition under D-C degradation.

    ``i_route``/``i_total`` require place→route net compatibility; while
    the toolchain emits no net mapping they stay UNKNOWN and QI falls
    back to ``i_place`` (same-netlist, EXACT) with downgraded evidence.
    """

    i_place: float | None
    i_route: float | None
    i_total: float | None
    congestion_severity: float | None
    compatibility_status: str


@dataclasses.dataclass(frozen=True)
class PowerObservation:
    """Raw power observation used by the QoR report and GUI breakdown."""

    total_uw: float | None
    budget_uw: float | None
    source_path: str | None
    source_kind: str | None  # signoff | synthesis
    corner: str | None


@dataclasses.dataclass(frozen=True)
class QorAnalysis:
    schema_version: int
    scoring_engine: str
    design: str
    workspace: str
    timestamp: str
    profile: str
    tclk_ns: float | None
    feasibility: Feasibility
    evidence: Evidence
    qor_record: dict  # dimension key -> QorDimension
    scalar_summary: ScalarSummary
    diagnoses: list
    inflation: InflationView
    power: PowerObservation
    flow_steps: dict  # step value -> persisted state snapshot
    config_warnings: list

    def to_dict(self) -> dict:
        return to_dict(self)

    @property
    def overall_score(self) -> float | None:
        return self.scalar_summary.score

    @property
    def dimension_scores(self) -> list:
        return sorted(self.qor_record.values(), key=lambda dim: dim.key)
