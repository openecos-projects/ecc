import json

from chipcompiler.cli.command_handlers.signoff_check import (
    _artifact_gate,
    _checker_gate,
    _flow_gate,
    _lec_gate,
    _netlist_artifact_gate,
    _overall,
    _qor_gate,
    _sta_gate,
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

    result = _checker_gate(tmp_path, "drc")
    assert result["status"] == "fail"
    assert result["failed_items"] == [""]


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


def test_lec_gate_requires_proven_result(tmp_path):
    output = tmp_path / "postRouteLec_kepler_formal" / "output"
    output.mkdir(parents=True)
    (output / "run_result.json").write_text('{"status": "proven"}', encoding="utf-8")

    assert _lec_gate(tmp_path)["status"] == "pass"


def test_artifact_gate_requires_one_nonempty_file(tmp_path):
    output = tmp_path / "Harden_ecc" / "output"
    output.mkdir(parents=True)
    artifact = output / "design.gds"
    artifact.write_bytes(b"gds")

    checklist = output.parent / "checklist.json"
    checklist.write_text(
        json.dumps(
            {
                "checklist": [
                    {
                        "title": "Harden GDS",
                        "state": "pass",
                        "source": {"path": "Harden_ecc/output/design.gds"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = _artifact_gate(tmp_path, "Harden GDS", "Harden_ecc/checklist.json")
    assert result["status"] == "pass"


def test_sta_gate_separates_setup_and_hold(tmp_path):
    checklist = tmp_path / "sta_ecc" / "checklist.json"
    checklist.parent.mkdir()
    checklist.write_text(
        json.dumps(
            {
                "checklist": [
                    {
                        "id": "sta.setup",
                        "title": "STA setup closure",
                        "category": "quality_gate",
                        "state": "pass",
                    },
                    {
                        "id": "sta.hold",
                        "title": "STA hold closure",
                        "category": "quality_gate",
                        "state": "fail",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _sta_gate(tmp_path, "setup")["status"] == "pass"
    assert _sta_gate(tmp_path, "hold")["status"] == "fail"


def test_flow_gate_reports_ongoing_as_fail(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "flow.json").write_text(json.dumps({"steps": [{"state": "Ongoing"}]}), encoding="utf-8")

    assert _flow_gate(tmp_path)["status"] == "fail"


def test_checker_gate_reports_drc_failure(tmp_path):
    checklist = tmp_path / "drc_ecc" / "checklist.json"
    checklist.parent.mkdir()
    checklist.write_text(
        json.dumps(
            {
                "checklist": [
                    {"category": "quality_gate", "state": "fail", "title": "DRC violations"}
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _checker_gate(tmp_path, "drc")["status"] == "fail"


def test_lec_gate_reports_non_proven(tmp_path):
    output = tmp_path / "postRouteLec_kepler_formal" / "output"
    output.mkdir(parents=True)
    (output / "run_result.json").write_text('{"status": "failed"}', encoding="utf-8")

    assert _lec_gate(tmp_path)["status"] == "fail"


def test_netlist_gate_rejects_external_path(tmp_path):
    output = tmp_path / "postRouteLec_kepler_formal" / "output"
    output.mkdir(parents=True)
    (output / "run_result.json").write_text(
        json.dumps({"gate_verilog": "/tmp/external.v.gz"}), encoding="utf-8"
    )

    result = _netlist_artifact_gate(tmp_path)
    assert result["status"] == "unknown"
    assert result["reason"] == "artifact_outside_workspace"
