"""Four-state signoff readiness (milestone vocabulary).

Maps checklist / assessment into PASS | WARN | MISS | ERROR without changing
the legacy ready / attention / blocked status fields.

In:
    schema-v3 signoff_checklist dict and/or assessment status
Out:
    Readiness — PASS | WARN | MISS | ERROR
Entry:
    build_signoff_assessment()  chipcompiler/engine/signoff_assessment.py
See:
    projection_lines()          test/lit/csv_gates/projection.py
    SIGNOFF_ITEM_CATALOG        chipcompiler/runtime/signoff/catalog.py
"""

from __future__ import annotations

from typing import Any, Literal

Readiness = Literal["PASS", "WARN", "MISS", "ERROR"]

_VALID = frozenset({"PASS", "WARN", "MISS", "ERROR"})
_QUALITY_CATEGORIES = frozenset({"quality", "quality_gate"})


def classify_signoff_readiness(
    checklist: dict[str, Any] | None = None,
    *,
    assessment_status: str | None = None,
    checklist_unavailable: bool = False,
) -> Readiness:
    """Classify readiness from a schema-v3 signoff checklist (or assessment status).

    Priority: ERROR (QoR gate fail) > MISS (missing evidence/artifacts) > WARN > PASS.

    Checklist marks missing files as ``state=failed`` with ``owner=checklist``;
    QoR gate failures use ``owner=qor``. Both are blocked, but only the latter is
    ERROR in the milestone vocabulary.

    In:
        checklist — schema-v3 signoff_checklist object, or None
        assessment_status — legacy ready|attention|blocked, optional
        checklist_unavailable — force MISS when checklist cannot be read
    Out:
        Readiness — PASS | WARN | MISS | ERROR
    Entry:
        attach_readiness()          chipcompiler/runtime/signoff/readiness.py
        build_signoff_assessment()  chipcompiler/engine/signoff_assessment.py
    See:
        projection_lines()          test/lit/csv_gates/projection.py
    """
    if checklist_unavailable:
        return "MISS"
    if not isinstance(checklist, dict) or not isinstance(checklist.get("checklist"), list):
        if assessment_status == "ready":
            return "PASS"
        if assessment_status == "attention":
            return "WARN"
        return "MISS"

    items = checklist["checklist"]
    saw_gate_fail = False
    saw_missing = False
    saw_attention = False

    for item in items:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", "unavailable"))
        blocked = bool(item.get("blocked"))
        owner = str(item.get("owner") or "checklist")
        category = str(item.get("category") or "")

        if blocked and state == "unavailable":
            saw_missing = True
        elif blocked and state == "failed":
            if owner == "qor" or category in _QUALITY_CATEGORIES:
                saw_gate_fail = True
            else:
                saw_missing = True
        elif state == "unavailable":
            saw_missing = True
        elif state == "failed" or state != "pass":
            saw_attention = True

    status = checklist.get("status")
    if status == "attention":
        saw_attention = True
    elif status == "blocked" and not saw_gate_fail and not saw_missing:
        saw_missing = True

    if saw_gate_fail:
        return "ERROR"
    if saw_missing:
        return "MISS"
    if saw_attention or status == "attention":
        return "WARN"
    if status == "ready" or assessment_status == "ready" or not items:
        return "PASS"
    if assessment_status == "attention":
        return "WARN"
    if assessment_status == "blocked":
        return "MISS"
    return "PASS"


def attach_readiness(
    assessment: dict[str, Any],
    checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp ``readiness`` (and ``items`` if absent) onto an assessment dict.

    In:
        assessment — mutable assessment mapping from engine
        checklist — schema-v3 checklist used for classify + item_summaries
    Out:
        dict — shallow copy of assessment with readiness (+ items)
    Entry:
        build_signoff_assessment()  chipcompiler/engine/signoff_assessment.py
    See:
        classify_signoff_readiness() chipcompiler/runtime/signoff/readiness.py
        item_summaries()             chipcompiler/runtime/signoff/readiness.py
    """
    unavailable = assessment.get("status") == "blocked" and any(
        risk.get("title") == "Signoff checklist unavailable"
        for risk in assessment.get("risks", [])
        if isinstance(risk, dict)
    )
    readiness = classify_signoff_readiness(
        checklist,
        assessment_status=str(assessment.get("status", "")),
        checklist_unavailable=unavailable,
    )
    if readiness not in _VALID:
        readiness = "MISS"
    out = dict(assessment)
    out["readiness"] = readiness
    if "items" not in out:
        out["items"] = item_summaries(checklist)
    return out


def item_summaries(checklist: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten checklist rows for assessment ``items``.

    In:
        checklist — schema-v3 signoff_checklist, or None
    Out:
        list[dict] — id/state/blocked/policy/owner/title/step/category
    See:
        attach_readiness()  chipcompiler/runtime/signoff/readiness.py
    """
    if not isinstance(checklist, dict) or not isinstance(checklist.get("checklist"), list):
        return []
    rows = []
    for item in checklist["checklist"]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            {
                "id": item.get("id"),
                "state": item.get("state", "unavailable"),
                "blocked": bool(item.get("blocked")),
                "policy": item.get("policy", "warn"),
                "owner": item.get("owner", "checklist"),
                "title": item.get("title", ""),
                "step": item.get("step", ""),
                "category": item.get("category", ""),
            }
        )
    return rows
