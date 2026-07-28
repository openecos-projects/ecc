import json
from pathlib import Path
from types import SimpleNamespace

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


def test_sta_checklist_references_v4_quality_gates_and_current_artifacts(tmp_path):
    report_root = tmp_path / "sta_ecc" / "report" / "MAX_125" / "RCworst"
    feature_root = tmp_path / "sta_ecc" / "feature" / "MAX_125" / "RCworst"
    _write(report_root / "qor_summary.rpt", "current STA report\n")
    _write(feature_root / "qor_summary.json", {"schema_version": 1})
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
    workspace = SimpleNamespace()
    step = SimpleNamespace(
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


def test_sta_checklist_blocks_missing_v4_gate_summary(tmp_path):
    checklist_path = tmp_path / "sta_ecc" / "checklist.json"
    workspace = SimpleNamespace()
    step = SimpleNamespace(
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
    workspace = SimpleNamespace(config={StepEnum.STA.value: ""})
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
