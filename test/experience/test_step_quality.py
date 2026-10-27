from types import SimpleNamespace

from ecc_experience.knowledge.step_quality import grade_case


def _step(*, complete=True):
    return {
        "step": "Synthesis",
        "state": "Success",
        "analysis_revision": "qor-analyzer-2" if complete else None,
        "metrics": [
            {
                "id": "cell_count",
                "status": "available",
                "scope": "design",
                "corner": "tt",
            }
        ],
        "resource_observation": {
            "measurement": {"scope": "isolated_process", "status": "available"}
        },
    }


def _case(level="applied"):
    return SimpleNamespace(
        case_id="case-a",
        parameter_evidence=level,
        failure=SimpleNamespace(primary_category="none"),
    )


def test_high_requires_complete_checks_and_repeat_stability():
    verification = SimpleNamespace(status="pass", integrity="pass")
    features = {"steps": [_step()]}

    medium = grade_case(_case(), verification, features)
    high = grade_case(_case(), verification, features, stability="consistent")

    assert medium["level"] == "medium"
    assert high["level"] == "high"
    assert high["steps"][0]["level"] == "high"


def test_configured_parameters_keep_quality_medium():
    result = grade_case(
        _case("configured"),
        SimpleNamespace(status="pass", integrity="pass"),
        {"steps": [_step()]},
        stability="consistent",
    )

    check = next(
        item for item in result["steps"][0]["checks"] if item["id"] == "parameter_materialization"
    )
    assert check["status"] == "unknown"
    assert result["level"] == "medium"


def test_failed_verification_forces_low_quality():
    result = grade_case(
        _case(),
        SimpleNamespace(status="fail", integrity="pass"),
        {"steps": [_step()]},
        stability="consistent",
    )

    assert result["level"] == "low"
