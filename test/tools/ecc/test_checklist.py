import json
from pathlib import Path

from chipcompiler.data import (
    ChecklistState,
    EccAnalysis,
    EccFeature,
    EccOutput,
    EccReport,
    EccStep,
    OriginDesign,
    StepEnum,
    Workspace,
)
from chipcompiler.tools.ecc.checklist import EccRcxChecklist, EccStaChecklist
from chipcompiler.tools.ecc.sta_qor import sta_qor_summary_paths


def _write(path: Path, data: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data) if isinstance(data, dict) else data
    path.write_text(text, encoding="utf-8")
    return path


def _gate(gate_id: str, title: str) -> dict:
    return {
        "id": gate_id,
        "title": title,
        "state": "pass",
        "blocking": True,
        "metrics": [],
        "evidence": [],
    }


def _sta_config(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "config" / "sta.json",
        {
            "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
            "signoff": [{"MAX": ["RCworst"]}],
        },
    )


def _sta_qor_summary() -> dict:
    return {
        "path_groups": [],
        "summary": {
            "setup": {"wns": 0.0, "tns": 0.0, "nvp": 0, "frequency_mhz": 100.0},
            "hold": {"wns": 0.0, "tns": 0.0, "nvp": 0},
        },
    }


def _sta_timing_paths() -> dict:
    return {
        "schema_version": 1,
        "corner": "MAX_125/RCworst",
        "path_limit": 20,
        "paths": [],
    }


def test_sta_checklist_references_v4_quality_gates_and_current_artifacts(tmp_path):
    report_root = tmp_path / "sta_ecc" / "report" / "MAX_125" / "RCworst"
    feature_root = tmp_path / "sta_ecc" / "feature" / "MAX_125" / "RCworst"
    _write(report_root / "qor_summary.rpt", "current STA report\n")
    _write(report_root / "timing_max.rpt", "current STA report\n")
    _write(feature_root / "qor_summary.json", _sta_qor_summary())
    _write(feature_root / "timing_paths.json", _sta_timing_paths())
    summary_path = _write(
        tmp_path / "sta_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "analysis_status": "valid",
            "quality_status": "pass",
            "gates": [
                _gate("qor.sta.setup_closed", "STA setup closure"),
                _gate("qor.sta.hold_closed", "STA hold closure"),
            ],
        },
    )
    checklist_path = tmp_path / "sta_ecc" / "checklist.json"
    workspace = Workspace(config={StepEnum.STA.value: _sta_config(tmp_path)})
    step = EccStep(
        name=StepEnum.STA.value,
        checklist=ChecklistState(path=checklist_path),
        analysis=EccAnalysis(qor_summary=summary_path),
        report=EccReport(dir=report_root.parent.parent),
        feature=EccFeature(dir=feature_root.parent.parent),
    )

    assert EccStaChecklist(workspace, step).check() is True

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in data["checklist"]}
    assert data["schema_version"] == 3
    assert items["quality.sta.setup_closed"]["owner"] == "qor"
    assert items["quality.sta.setup_closed"]["state"] == "pass"
    assert items["quality.sta.hold_closed"]["state"] == "pass"
    assert items["report.sta.timing_reports"]["state"] == "pass"
    assert items["artifact.sta.corner_summaries"]["state"] == "pass"
    assert items["artifact.sta.timing_paths"]["state"] == "pass"
    assert {entry["path"] for entry in items["report.sta.timing_reports"]["evidence"]} == {
        str(report_root / "qor_summary.rpt"),
        str(report_root / "timing_max.rpt"),
    }


def test_sta_checklist_rejects_obsolete_report_names_and_missing_current_artifacts(tmp_path):
    report_root = tmp_path / "sta_ecc" / "report" / "MAX_125" / "RCworst"
    feature_root = tmp_path / "sta_ecc" / "feature" / "MAX_125" / "RCworst"
    _write(report_root / "qor_summary.rpt", "current STA report\n")
    _write(report_root / "timing_max_in2out.rpt", "obsolete STA report\n")
    _write(feature_root / "qor_summary.json", _sta_qor_summary())
    _write(feature_root / "timing_paths.json", {})
    summary_path = _write(
        tmp_path / "sta_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "analysis_status": "valid",
            "quality_status": "pass",
            "gates": [
                _gate("qor.sta.setup_closed", "STA setup closure"),
                _gate("qor.sta.hold_closed", "STA hold closure"),
            ],
        },
    )
    checklist_path = tmp_path / "sta_ecc" / "checklist.json"
    workspace = Workspace(config={StepEnum.STA.value: _sta_config(tmp_path)})
    step = EccStep(
        name=StepEnum.STA.value,
        checklist=ChecklistState(path=checklist_path),
        analysis=EccAnalysis(qor_summary=summary_path),
        report=EccReport(dir=report_root.parent.parent),
        feature=EccFeature(dir=feature_root.parent.parent),
    )

    assert EccStaChecklist(workspace, step).check() is False

    items = {
        item["id"]: item
        for item in json.loads(checklist_path.read_text(encoding="utf-8"))["checklist"]
    }
    assert items["report.sta.timing_reports"]["state"] == "failed"
    assert items["report.sta.timing_reports"]["blocked"] is True
    assert "MAX_125/RCworst/timing_max.rpt" in items["report.sta.timing_reports"]["summary"]
    assert items["artifact.sta.timing_paths"]["state"] == "failed"
    assert items["artifact.sta.timing_paths"]["blocked"] is True
    assert all(
        not entry["path"].endswith("timing_max_in2out.rpt")
        for entry in items["report.sta.timing_reports"]["evidence"]
    )


def test_sta_checklist_blocks_missing_v4_gate_summary(tmp_path):
    checklist_path = tmp_path / "sta_ecc" / "checklist.json"
    workspace = Workspace()
    step = EccStep(
        name=StepEnum.STA.value,
        checklist=ChecklistState(path=checklist_path),
        analysis=EccAnalysis(qor_summary=tmp_path / "sta_ecc" / "analysis" / "qor_summary.json"),
        report=EccReport(dir=tmp_path / "sta_ecc" / "report"),
        feature=EccFeature(dir=tmp_path / "sta_ecc" / "feature"),
    )

    assert EccStaChecklist(workspace, step).check() is False

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in data["checklist"]}
    assert items["quality.sta.setup_closed"]["state"] == "unavailable"
    assert items["quality.sta.setup_closed"]["blocked"] is True


def test_sta_summary_paths_do_not_fallback_to_obsolete_output(tmp_path):
    workspace = Workspace()
    feature_root = tmp_path / "feature"
    output_path = tmp_path / "output" / "MAX_125" / "RCworst" / "qor_summary.json"
    _write(output_path, {"schema_version": 1})

    assert sta_qor_summary_paths(workspace, feature_root) == []


def test_collect_rcx_spef_paths_appends_discovered_spefs_to_live_output_list(tmp_path):
    # Legacy contract: output.get("spef", []) returned the builder's own list, so
    # extend(glob(...)) added discovered output-dir SPEFs to step.output.spef in place.
    # The typed reader must preserve that live-list mutation, not copy.
    output_dir = tmp_path / "rcx_ecc" / "output"
    _write(output_dir / "discovered.spef", "* spef\n")

    workspace = Workspace(design=OriginDesign(name="gcd", top_module="gcd"))
    workspace_step = EccStep(
        name=StepEnum.RCX.value,
        output=EccOutput(spef=[], dir=output_dir),
    )
    # init_checklist=False: exercise only the SPEF reader, not checklist building.
    checker = EccRcxChecklist(workspace, workspace_step, init_checklist=False)

    returned = checker.collect_rcx_spef_paths()

    assert returned == [str(output_dir / "discovered.spef")]
    # the discovered SPEF is reflected on the step's live output list (main parity)
    assert workspace_step.output.spef == [str(output_dir / "discovered.spef")]
