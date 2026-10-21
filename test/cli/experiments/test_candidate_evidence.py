import pytest

from chipcompiler.cli.experiments.candidate_evidence import candidate_evidence


@pytest.fixture
def evidence():
    return {
        "flow": {"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]},
        "checklist": {
            "status": "ready",
            "checklist": [{"id": "sta.setup", "step": "sta", "state": "pass", "blocked": False}],
        },
        "qor": {"scalar_summary": {"score": 93.6, "status": "GREEN"}},
        "exit_code": 0,
        "status_code": 0,
        "signoff_code": 0,
        "signoff_payload": [
            {"signoff": "check", "status": "pass"},
            *[
                {"gate": gate, "violation_count": 0}
                for gate in ("drc_clean", "lvs_clean", "sta_setup_clean", "sta_hold_clean")
            ],
        ],
    }


def test_candidate_uses_workspace_schema(evidence):
    assert candidate_evidence(**evidence) == {
        "status": "passed",
        "step_statuses": [{"name": "sta", "status": "success", "checklist": "passed"}],
        "qor_score": 93.6,
        "violation_count": 0,
        "signoff_exit_code": 0,
        "workspace_status_exit_code": 0,
    }


@pytest.mark.parametrize(
    ("code", "verdict", "expected"),
    [
        (7, "unknown", "unknown"),
        (6, "fail", "failed"),
        (2, "unknown", "failed"),
        (0, "unknown", "unknown"),
        (0, "fail", "unknown"),
    ],
)
def test_candidate_never_passes_unknown_or_failed_signoff(evidence, code, verdict, expected):
    evidence.update(signoff_code=code, signoff_payload=[{"signoff": "check", "status": verdict}])
    result = candidate_evidence(**evidence)
    assert result["status"] == expected
    assert result["violation_count"] == "unknown"


@pytest.mark.parametrize(
    "qor",
    [
        {},
        {"scalar_summary": {"score": None, "status": "NOT_RATED"}},
        {"score": True},
        {"score": float("nan")},
    ],
)
def test_missing_qor_is_unranked_and_not_passed(evidence, qor):
    evidence["qor"] = qor
    result = candidate_evidence(**evidence)
    assert result["status"] == "unknown"
    assert result["qor_score"] is None


def test_blocked_checklist_and_projected_step_are_preserved(evidence):
    evidence["checklist"]["status"] = "blocked"
    evidence["checklist"]["checklist"][0].update(state="failed", blocked=True)
    evidence["signoff_code"] = 6
    result = candidate_evidence(**evidence)
    assert result["status"] == "blocked"
    assert result["step_statuses"] == [{"name": "sta", "status": "success", "checklist": "blocked"}]
    evidence["checklist"] = {"status": "ready", "checklist": []}
    evidence["flow"]["steps"][0]["checklist_status"] = {"status": "blocked", "blocked": True}
    assert candidate_evidence(**evidence)["status"] == "blocked"


@pytest.mark.parametrize("state", ["Incomplete", "Failed", "Invalid", "Ongoing", "Unstart"])
def test_candidate_requires_complete_flow(evidence, state):
    evidence["flow"]["steps"][0]["state"] = state
    expected = "failed" if state in {"Incomplete", "Failed", "Invalid"} else "unknown"
    assert candidate_evidence(**evidence)["status"] == expected


def test_checker_count_sums_distinct_gates(evidence):
    evidence["signoff_payload"][2]["violation_count"] = 4
    evidence["signoff_payload"][3]["violation_count"] = 2
    assert candidate_evidence(**evidence)["violation_count"] == 6
    evidence["signoff_payload"][4]["violation_count"] = None
    assert candidate_evidence(**evidence)["violation_count"] == "unknown"
