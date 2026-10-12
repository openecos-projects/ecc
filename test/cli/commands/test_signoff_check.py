import json

from chipcompiler.cli.command_handlers.signoff_check import (
    _checker_gate,
    _flow_gate,
    _overall,
    _qor_gate,
)


def test_flow_gate_requires_all_steps_success(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"state": "Success"}, {"state": "Ongoing"}]}),
        encoding="utf-8",
    )

    assert _flow_gate(tmp_path)["status"] == "fail"


def test_qor_gate_does_not_treat_missing_score_as_pass(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "qor_report.json").write_text("{}", encoding="utf-8")

    assert _qor_gate(tmp_path)["status"] == "unknown"


def test_checker_gate_reports_failed_checklist_evidence(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        json.dumps({"checklist": [{"category": "drc", "state": "fail"}]}),
        encoding="utf-8",
    )

    assert _checker_gate(tmp_path, "drc")["status"] == "fail"


def test_checker_gate_reads_step_checklist_and_quality_gate(tmp_path):
    checklist = tmp_path / "drc_ecc" / "checklist.json"
    checklist.parent.mkdir()
    checklist.write_text(
        json.dumps(
            {
                "checklist": [
                    {"category": "quality_gate", "state": "pass"},
                    {"category": "artifact", "state": "pass"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _checker_gate(tmp_path, "drc")
    assert result["status"] == "pass"
    assert result["source"] == "drc_ecc/checklist.json"


def test_overall_preserves_unknown_when_no_gate_fails():
    assert _overall({"a": {"status": "pass"}, "b": {"status": "unknown"}}) == "unknown"
    assert _overall({"a": {"status": "fail"}, "b": {"status": "unknown"}}) == "fail"
