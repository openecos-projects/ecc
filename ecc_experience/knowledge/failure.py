"""Classify failures only from structured flow and acceptance evidence."""

from ecc_experience.models import FailureIdentity

FAILURE_CLASSIFIER = "failure-taxonomy/1"
_CANCELLED = {"cancel", "cancelled", "canceled", "interrupted", "terminated"}
_RESOURCE_OUTCOMES = {"oom", "out_of_memory", "timeout", "timed_out"}


def classify_failure(facts: dict, *, verification_status: str | None = None) -> FailureIdentity:
    if verification_status == "fail":
        return FailureIdentity(
            primary_category="evidence_invalid",
            contributing_factors=["case_verification_failed"],
            classifier_version=FAILURE_CLASSIFIER,
        )
    flow = facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        return FailureIdentity(
            primary_category="unknown",
            contributing_factors=["flow_unavailable"],
            classifier_version=FAILURE_CLASSIFIER,
        )
    if not steps:
        return FailureIdentity(
            primary_category="unknown",
            contributing_factors=["flow_empty"],
            classifier_version=FAILURE_CLASSIFIER,
        )

    cause = facts.get("cause")
    cause_text = cause.casefold() if isinstance(cause, str) else ""
    states = [str(step.get("state", "")).casefold() for step in steps]
    factors: list[str] = []
    references: list[str] = []
    if any(value in _CANCELLED for value in states) or any(
        value in cause_text for value in _CANCELLED
    ):
        return FailureIdentity(
            primary_category="cancelled",
            contributing_factors=["structured_cancellation_state"],
            classifier_version=FAILURE_CLASSIFIER,
            evidence=["flow.step.state"] if cause_text else ["flow.step.state", "cause"],
        )

    for step in steps:
        name = str(step.get("name", "unknown"))
        observation = step.get("resource_observation")
        outcome = observation.get("outcome") if isinstance(observation, dict) else None
        if isinstance(outcome, str) and outcome.casefold() in _RESOURCE_OUTCOMES:
            factors.append(f"resource_outcome:{name}:{outcome.casefold()}")
            references.append(f"flow.steps[{name}].resource_observation.outcome")
    if factors:
        return FailureIdentity(
            primary_category="resource",
            contributing_factors=sorted(set(factors)),
            classifier_version=FAILURE_CLASSIFIER,
            evidence=sorted(set(references)),
        )

    signoff = facts.get("signoffAssessment")
    signoff_status = str(signoff.get("status", "")).casefold() if isinstance(signoff, dict) else ""
    qor = facts.get("qorSnapshotExtension")
    feasibility = qor.get("feasibility") if isinstance(qor, dict) else None
    feasibility_status = (
        str(feasibility.get("status", "")).casefold() if isinstance(feasibility, dict) else ""
    )
    if all(value in {"success", "succeeded"} for value in states) and (
        signoff_status in {"failed", "blocked", "fail"} or feasibility_status == "fail"
    ):
        return FailureIdentity(
            primary_category="design_constraint",
            contributing_factors=[
                item
                for item in (
                    f"signoff:{signoff_status}" if signoff_status else None,
                    f"feasibility:{feasibility_status}" if feasibility_status else None,
                )
                if item is not None
            ],
            classifier_version=FAILURE_CLASSIFIER,
            evidence=[
                key
                for key in ("signoffAssessment.status", "qorSnapshotExtension.feasibility.status")
                if key.split(".")[0] in facts
            ],
        )

    failed = [
        str(step.get("name", "unknown"))
        for step in steps
        if str(step.get("state", "")).casefold()
        in {"error", "failed", "failure", "incomplete", "blocked"}
    ]
    if failed:
        return FailureIdentity(
            primary_category="tool_failure",
            contributing_factors=[f"flow_step:{name}:failed" for name in sorted(set(failed))],
            classifier_version=FAILURE_CLASSIFIER,
            evidence=["flow.step.state"],
        )
    if all(value in {"success", "succeeded"} for value in states):
        return FailureIdentity(
            primary_category="none",
            contributing_factors=[],
            classifier_version=FAILURE_CLASSIFIER,
            evidence=["flow.step.state"],
        )
    return FailureIdentity(
        primary_category="unknown",
        contributing_factors=["flow_state_unclassified"],
        classifier_version=FAILURE_CLASSIFIER,
        evidence=["flow.step.state"],
    )
