"""Deterministic lexicographic intervention prioritization (spec §11.4).

Interventions are hypotheses, never promises: every record names its
validation procedure and diagnosis confidence is kept separate from
intervention confidence (C_diagnosis != C_intervention).
"""

from chipcompiler.analysis.qor.models import Intervention

TIER_1 = "TIER_1_FEASIBILITY"
TIER_2 = "TIER_2_BOTTLENECK"
TIER_3 = "TIER_3_OPPORTUNITY"

_TIER_ORDER = {TIER_1: 0, TIER_2: 1, TIER_3: 2}


def make(hypothesis, tier, confidence="LOW", parameter_knob=None, validation_procedure=None):
    return Intervention(
        hypothesis=hypothesis,
        tier=tier,
        confidence=confidence,
        parameter_knob=parameter_knob,
        validation_procedure=validation_procedure,
    )


def prioritize(diagnoses) -> list:
    """Flatten diagnosis interventions under the strict three-tier policy.

    Tier 1 (feasibility blockers) precedes Tier 2 (quality limiters),
    which precedes Tier 3 (optimization opportunities); within a tier,
    the parent diagnosis severity decides, then diagnosis id for a total
    deterministic order.
    """
    decorated = []
    for diagnosis in diagnoses:
        for intervention in diagnosis.interventions:
            decorated.append(
                (
                    _TIER_ORDER[intervention.tier],
                    -diagnosis.severity,
                    diagnosis.diagnosis_id,
                    intervention,
                )
            )
    decorated.sort(key=lambda item: item[:3])
    return [item[3] for item in decorated]
