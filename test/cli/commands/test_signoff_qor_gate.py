import json

import pytest

from chipcompiler.cli.command_handlers.signoff_check import _qor_gate


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ({"scalar_summary": {"score": 88.1, "status": "GREEN"}}, "pass"),
        ({"score": 0}, "pass"),
        ({"qor_score": 88.1}, "pass"),
        ({"scalar_summary": {"score": 0, "status": "NOT_RATED"}}, "unknown"),
        ({"score": float("nan")}, "unknown"),
        ({"score": True}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_signoff_qor_uses_canonical_available_score(tmp_path, report, expected):
    home = tmp_path / "home"
    home.mkdir()
    (home / "qor_report.json").write_text(json.dumps(report))

    assert _qor_gate(tmp_path)["status"] == expected
