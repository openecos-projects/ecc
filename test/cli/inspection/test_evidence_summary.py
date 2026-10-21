import pytest

from chipcompiler.cli.inspection.evidence_summary import flow_status


@pytest.mark.parametrize(
    ("required_state", "expected"),
    [
        ("Success", "success"),
        ("Unstart", "partial"),
        ("Ongoing", "ongoing"),
        ("Incomplete", "failed"),
    ],
)
def test_flow_status_keeps_advisory_identity(required_state, expected):
    flow = {
        "steps": [
            {"name": "antennaCheck", "state": "Incomplete"},
            {"name": "emir", "state": "Incomplete"},
            {"name": "Harden", "state": required_state},
        ]
    }

    assert flow_status(flow) == expected
    assert flow["steps"][0]["state"] == "Incomplete"
