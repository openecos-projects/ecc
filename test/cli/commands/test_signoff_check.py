import json

import pytest

from chipcompiler.cli.command_handlers.signoff_check import (
    _artifact_gate,
    _checker_gate,
    _flow_gate,
    _lec_gate,
    _metric_checker_gate,
    _netlist_artifact_gate,
    _overall,
    _qor_gate,
    _sta_gate,
)


def _write_metric(root, step, metrics):
    path = root / f"{step}_ecc" / "analysis" / "qor_metrics.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": step,
                "tool": "ecc",
                "status": "success",
                "metrics": [
                    {"id": metric, "value": value, "unit": "count"}
                    for metric, value in metrics.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


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


def test_metric_checker_gate_uses_zero_as_clean(tmp_path):
    path = _write_metric(tmp_path, "drc", {"drc_count": 0})

    result = _metric_checker_gate(tmp_path, "drc")

    assert result["status"] == "pass"
    assert result["violation_count"] == 0
    assert result["source"] == str(path)
    assert result["stale"] is False
    assert result["provisional"] is False


def test_metric_checker_gate_reports_real_count_not_checklist_count(tmp_path):
    path = _write_metric(tmp_path, "drc", {"drc_count": 7})

    result = _metric_checker_gate(tmp_path, "drc")

    assert result["status"] == "fail"
    assert result["reason"] == "drc_violations"
    assert result["violation_count"] == 7
    assert result["failed_items"] == ["drc=7"]
    assert result["source"] == str(path)


def test_metric_checker_gate_separates_sta_setup_and_hold(tmp_path):
    _write_metric(
        tmp_path,
        "sta",
        {"sta_setup_violation_count": 0, "sta_hold_violation_count": 3},
    )

    setup = _metric_checker_gate(tmp_path, "sta", "sta_setup_violation_count")
    hold = _metric_checker_gate(tmp_path, "sta", "sta_hold_violation_count")

    assert setup["status"] == "pass"
    assert setup["violation_count"] == 0
    assert hold["status"] == "fail"
    assert hold["violation_count"] == 3


def test_metric_checker_gate_does_not_treat_missing_count_as_clean(tmp_path):
    _write_metric(tmp_path, "drc", {"route_dr_total_violation_count": 0})

    result = _metric_checker_gate(tmp_path, "drc")

    assert result["status"] == "unknown"
    assert result["violation_count"] is None
    assert result["provisional"] is True


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
    assert (
        _overall(
            {"required": {"status": "pass"}, "informational": {"status": "unknown"}},
            ("required",),
        )
        == "pass"
    )


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


def test_contract_gate_normalizes_optional_evidence_fields():
    from chipcompiler.cli.command_handlers.signoff_check import _contract_gate

    result = _contract_gate({"status": "fail", "reason": "drc_violations", "violation_count": 4})

    assert result == {
        "status": "fail",
        "reason": "drc_violations",
        "source": None,
        "failed_items": [],
        "violation_count": 4,
        "stale": False,
        "provisional": False,
    }


def test_contract_gate_preserves_artifact_identity_fields():
    from chipcompiler.cli.command_handlers.signoff_check import _contract_gate

    result = _contract_gate(
        {
            "status": "pass",
            "source": "Harden_ecc/output/design.gds",
            "bytes": 12,
            "sha256": "abc",
        }
    )

    assert result["bytes"] == 12
    assert result["sha256"] == "abc"
    assert result["stale"] is False
    assert result["provisional"] is False


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [("pass", 0), ("fail", 6), ("unknown", 7)],
)
def test_signoff_contract_exit_code_matrix(monkeypatch, tmp_path, status, expected_code):
    from types import SimpleNamespace

    import chipcompiler.cli.command_handlers.signoff_check as module
    from chipcompiler.cli.core.types import CommandContext

    home = tmp_path / "home"
    home.mkdir()
    (home / "flow.json").write_text(json.dumps({"steps": [{"state": "Success"}]}), encoding="utf-8")
    (home / "qor_report.json").write_text(json.dumps({"score": 90}), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "resolve_loaded_workspace",
        lambda command_input, ctx: (SimpleNamespace(directory=str(tmp_path)), None),
    )
    monkeypatch.setattr(module, "workspace_display", lambda command_input, ctx: "default")
    monkeypatch.setattr(
        "chipcompiler.engine.signoff_export.inspect_signoff_package",
        lambda workspace: {"status": "ready"},
    )
    gates = {name: {"status": status} for name in module._PROFILES["rtl2gds"]}
    monkeypatch.setattr(module, "_flow_gate", lambda root: gates["flow_complete"])
    monkeypatch.setattr(module, "_qor_gate", lambda root: gates["qor_available"])
    monkeypatch.setattr(module, "_checklist_gate", lambda review: gates["checklist_ready"])
    monkeypatch.setattr(module, "_metric_checker_gate", lambda root, *args: {"status": status})
    result = module.check(
        SimpleNamespace(profile="rtl2gds"),
        CommandContext("", None, "", None, SimpleNamespace(value="json")),
    )
    assert result.exit_code == expected_code
    assert result.records[0]["status"] == status
    assert all("status" in record for record in result.records[1:])
