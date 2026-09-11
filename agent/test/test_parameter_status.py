from types import SimpleNamespace

import pytest

from agent.data.parameter_runtime_observer import _build_dreamplace_report


@pytest.mark.parametrize(
    "overflow,status,actual",
    [
        (0.08, "effective", 0.1),
        (0.1, "inactive", None),
        (0.3, "inactive", None),
        (None, "unknown", None),
        (-1, "unknown", None),
    ],
)
def test_overflow_final_threshold(overflow, status, actual):
    report = _build_dreamplace_report(
        {"knob_id": "place.target_overflow", "value": 0.1},
        SimpleNamespace(params=SimpleNamespace(stop_overflow=0.1)),
        {"overflow": overflow},
        {},
        engine_succeeded=True,
    )
    assert (report["status"], report["actual_value"]) == (status, actual)
