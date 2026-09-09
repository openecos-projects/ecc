"""Deterministic diagnosis and intervention engine (spec §11).

Observations use strictly non-causal language: cross-stage deltas are
"consumed" or "associated", never "caused". Severities are closed-form;
signoff gate violations always outrank quality bottlenecks
(Sgate >= 0.80 > Sbottleneck) while keeping magnitude information.
"""

from chipcompiler.analysis.qor import interventions as iv
from chipcompiler.analysis.qor.calibration import (
    HARDEN_DELIVERABLE_COUNT,
    OVER_PROVISION_FRACTION,
    TAU_DRC_REF,
    TAU_LVS_REF,
    TIMING_FAIL_FRACTION,
    clamp01,
)
from chipcompiler.analysis.qor.models import Diagnosis, SupportingMetric

# Quality dimensions start counting as bottlenecks below this coordinate.
BOTTLENECK_THRESHOLD = 80.0


def build_diagnoses(feasibility, dimensions, bundle, inputs) -> list:
    diagnoses = []
    for gate in feasibility.gates:
        if gate.state == "failed":
            diagnoses.append(_gate_diagnosis(gate, inputs))
    if feasibility.status != "PHYSICAL_FAIL":
        for dimension in dimensions.values():
            if dimension.value is not None and dimension.value < BOTTLENECK_THRESHOLD:
                diagnoses.append(_bottleneck_diagnosis(dimension))
        diagnoses.extend(_opportunity_diagnoses(bundle, inputs))
        if bundle.congestion_severity is not None and bundle.congestion_severity > 0:
            diagnoses.append(_congestion_diagnosis(bundle))
    return sorted(diagnoses, key=lambda d: (-d.severity, d.diagnosis_id))


def _supporting(inputs, metric_id, unit=""):
    record = inputs.metrics.get(metric_id)
    if record is None:
        return None
    return SupportingMetric(
        name=metric_id,
        value=record.value,
        unit=unit or record.unit,
        source=inputs.source_path(metric_id),
    )


def _gate_magnitude(gate, inputs):
    """Normalized violation magnitude in (0, 1] for a failed gate (eq. 49-54)."""
    value = inputs.value(gate.metrics[0]) if gate.metrics else None
    if value is None:
        return 1.0
    if gate.id in ("GATE_SETUP_SLACK", "GATE_HOLD_SLACK"):
        scale = TIMING_FAIL_FRACTION * inputs.tclk_ns if inputs.tclk_ns else None
        if not scale:
            return 1.0
        return max(clamp01(abs(value) / scale), 1e-9)
    if gate.id in ("GATE_SETUP_NVP", "GATE_HOLD_NVP"):
        # Per-endpoint normalization needs the endpoint population, which
        # the artifacts do not carry; any violation counts as full band.
        return 1.0
    if gate.id == "GATE_DRC":
        return max(clamp01(value / TAU_DRC_REF), 1e-9)
    if gate.id == "GATE_LVS":
        return max(clamp01(value / TAU_LVS_REF), 1e-9)
    if gate.id == "GATE_HARDEN_ARTIFACTS":
        return max(clamp01(value / HARDEN_DELIVERABLE_COUNT), 1e-9)
    return 1.0


def _gate_diagnosis(gate, inputs) -> Diagnosis:
    magnitude = _gate_magnitude(gate, inputs)
    severity = 0.80 + 0.20 * magnitude
    support = [
        metric
        for metric in (_supporting(inputs, metric_id) for metric_id in gate.metrics)
        if metric is not None
    ]
    if gate.id in ("GATE_SETUP_SLACK", "GATE_HOLD_SLACK"):
        interpretation = (
            f"{gate.stage} signed worst slack is negative; {abs(support[0].value):g} ns of "
            "violation magnitude is present in the signoff timing reports."
            if support
            else f"{gate.stage} signoff slack gate failed."
        )
        hypothesis = (
            "Review the failing signoff timing paths and evaluate placement/routing "
            "adjustments correlated with slack recovery."
        )
        validation = "Rerun STA after implementation changes to confirm slack >= 0."
    else:
        interpretation = (
            f"{gate.stage} signoff reports {support[0].value:g} violation(s); "
            "tapeout feasibility is blocked."
            if support
            else f"{gate.stage} signoff gate failed."
        )
        hypothesis = (
            f"Inspect the {gate.stage} violation reports and evaluate a corrective rerun "
            "of the responsible implementation step."
        )
        validation = f"Rerun the {gate.stage} signoff check and confirm a clean result."
    return Diagnosis(
        diagnosis_id=f"diag.signoff.{gate.id.lower()}",
        state="FAIL",
        severity=severity,
        diagnosis_confidence="HIGH",
        trigger_features=[],
        supporting_metrics=support,
        interpretation=interpretation,
        affected_dimensions=[gate.stage.lower()],
        interventions=[
            iv.make(
                f"Intervention hypothesis: {hypothesis}",
                iv.TIER_1,
                confidence="MEDIUM",
                validation_procedure=validation,
            )
        ],
        intervention_confidence="MEDIUM",
        validation_required=validation,
    )


def _bottleneck_diagnosis(dimension) -> Diagnosis:
    severity = clamp01((100.0 - dimension.value) / 100.0)
    knob = _DIMENSION_KNOBS.get(dimension.key, {})
    hypothesis = knob.get(
        "hypothesis",
        f"Evaluate parameter adjustments correlated with {dimension.key} quality recovery.",
    )
    validation = knob.get(
        "validation", "Rerun the flow after the change and compare the affected QoR dimension."
    )
    return Diagnosis(
        diagnosis_id=f"diag.quality.{dimension.key}",
        state=dimension.state if dimension.state in ("WATCH", "FAIL") else "WATCH",
        severity=severity,
        diagnosis_confidence="HIGH",
        trigger_features=[feature.feature_id for feature in dimension.features],
        supporting_metrics=[],
        interpretation=(
            f"{dimension.key} quality coordinate {dimension.value:.1f} is below the "
            f"{BOTTLENECK_THRESHOLD:g}-point bottleneck threshold."
        ),
        affected_dimensions=[dimension.key],
        interventions=[
            iv.make(
                f"Intervention hypothesis: {hypothesis}",
                iv.TIER_2,
                confidence=knob.get("confidence", "LOW"),
                parameter_knob=knob.get("knob"),
                validation_procedure=validation,
            )
        ],
        intervention_confidence=knob.get("confidence", "LOW"),
        validation_required=validation,
    )


_DIMENSION_KNOBS = {
    "interconnect": {
        "hypothesis": (
            "evaluate increased router search depth correlated with wirelength reduction."
        ),
        "knob": "route.dr_search_depth",
        "validation": "Requires a trial reroute to confirm wirelength reduction.",
        "confidence": "LOW",
    },
    "area": {
        "hypothesis": "evaluate core utilization targets closer to the placement sweet spot.",
        "validation": "Rerun floorplacement and compare area quality.",
    },
    "power": {
        "hypothesis": "review the declared power budget against measured signoff power.",
        "validation": "Rerun STA power analysis after power-focused optimization.",
    },
    "robustness": {
        "hypothesis": "evaluate clock tree balancing and multi-corner skew targets.",
        "validation": "Rerun CTS and signoff STA to compare dispersion.",
    },
}


def _opportunity_diagnoses(bundle, inputs) -> list:
    diagnoses = []
    ws = inputs.value("sta_setup_wns")
    tclk = inputs.tclk_ns
    if ws is not None and tclk:
        over = OVER_PROVISION_FRACTION * tclk
        if ws > over:
            severity = clamp01((ws - over) / (tclk - over))
            support = _supporting(inputs, "sta_setup_wns", "ns")
            validation = (
                "Requires downsizing trials with signoff STA re-check to confirm timing holds."
            )
            diagnoses.append(
                Diagnosis(
                    diagnosis_id="diag.timing.over_provisioned",
                    state="OPPORTUNITY",
                    severity=severity,
                    diagnosis_confidence="HIGH",
                    trigger_features=["F_STA_HEADROOM"],
                    supporting_metrics=[support] if support else [],
                    interpretation=(
                        f"Timing margin (+{ws:g}ns) exceeds the over-provisioning threshold "
                        f"({over:g}ns); the design appears over-constrained."
                    ),
                    affected_dimensions=["timing", "area", "power"],
                    interventions=[
                        iv.make(
                            "Intervention hypothesis: downsize drive strengths to recover "
                            "power and area correlated with the excess margin.",
                            iv.TIER_3,
                            confidence="MEDIUM",
                            validation_procedure=validation,
                        )
                    ],
                    intervention_confidence="MEDIUM",
                    validation_required=validation,
                )
            )
    return diagnoses


def _congestion_diagnosis(bundle) -> Diagnosis:
    severity = min(1.0, bundle.congestion_severity)
    validation = "Rerun placement/routing after density adjustments and compare overflow."
    return Diagnosis(
        diagnosis_id="diag.place.congestion",
        state="WATCH",
        severity=severity,
        diagnosis_confidence="HIGH",
        trigger_features=["F_PL_CONG_CONC", "S_CONG"],
        supporting_metrics=[],
        interpretation=(
            "Placement congestion proxies are associated with elevated routing demand "
            f"(severity {severity:g})."
        ),
        affected_dimensions=["interconnect"],
        interventions=[
            iv.make(
                "Intervention hypothesis: evaluate placement density or routing capacity "
                "adjustments correlated with overflow reduction.",
                iv.TIER_2,
                confidence="LOW",
                validation_procedure=validation,
            )
        ],
        intervention_confidence="LOW",
        validation_required=validation,
    )
