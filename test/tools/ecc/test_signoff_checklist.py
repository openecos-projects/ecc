import json
from pathlib import Path

from chipcompiler.data import OriginDesign, StateEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.metrics import _quality_gates
from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist


def _record(metric_id, value, path="feature/step.json"):
    return {
        "id": metric_id,
        "value": value,
        "source": {"kind": "feature", "path": path, "selector": f"/{metric_id}"},
    }


def test_quality_gates_only_include_final_drc_rcx_and_sta(tmp_path):
    drc = WorkspaceStep(name=StepEnum.DRC.value, directory=tmp_path / "drc_ecc")
    drc_gates = _quality_gates(drc, [_record("drc_count", 0)])
    assert drc_gates == [
        {
            "id": "qor.drc.clean",
            "title": "Final DRC clean",
            "state": "pass",
            "blocking": True,
            "metrics": [
                {
                    "id": "drc_count",
                    "actual": 0,
                    "operator": "==",
                    "expected": 0,
                    "source": _record("drc_count", 0)["source"],
                }
            ],
            "evidence": [_record("drc_count", 0)["source"]],
        }
    ]

    route = WorkspaceStep(name=StepEnum.ROUTING.value, directory=tmp_path / "route_ecc")
    assert _quality_gates(route, [
        _record("route_dr_total_violation_count", 4),
        _record("route_la_total_overflow", 9),
    ]) == []


def test_sta_quality_gates_require_all_corner_coverage_and_closure(tmp_path):
    feature_path = tmp_path / "sta_ecc" / "feature" / "sta.step.json"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text(json.dumps({
        "sta": {
            "signoff_metrics": {
                "coverage": {"status": "pass"},
                "setup": {"status": "blocked"},
                "hold": {"status": "pass"},
            }
        }
    }), encoding="utf-8")
    step = WorkspaceStep(
        name=StepEnum.STA.value,
        directory=tmp_path / "sta_ecc",
        feature={"step": feature_path},
    )
    gates = {gate["id"]: gate for gate in _quality_gates(step, [
        _record("sta_setup_wns", -0.01),
        _record("sta_setup_tns", -1),
        _record("sta_setup_violation_count", 1),
        _record("sta_hold_wns", 0.1),
        _record("sta_hold_tns", 0),
        _record("sta_hold_violation_count", 0),
    ])}
    assert gates["qor.sta.setup_closed"]["state"] == "failed"
    assert gates["qor.sta.hold_closed"]["state"] == "pass"


def test_step_checklist_references_v4_qor_gate_without_recomputing_it(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    (tmp_path / "home").mkdir()
    workspace.home.init(tmp_path / "home" / "home.json")
    workspace.home.set_checklist(tmp_path / "home" / "checklist.json")
    workspace.flow.data = {
        "steps": [
            {"name": step.value, "state": StateEnum.Success.value}
            for step in (
                StepEnum.ROUTING,
                StepEnum.DRC,
                StepEnum.FILLER,
                StepEnum.RCX,
                StepEnum.STA,
                StepEnum.HARDEN,
            )
        ]
    }
    summary_path = tmp_path / "drc_ecc" / "analysis" / "qor_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps({
        "schema_version": 4,
        "gates": [{
            "id": "qor.drc.clean",
            "title": "Final DRC clean",
            "state": "failed",
            "blocking": True,
            "metrics": [{"id": "drc_count", "actual": 2, "operator": "==", "expected": 0}],
            "evidence": [{"kind": "feature", "path": "feature/drc.step.json"}],
        }],
    }), encoding="utf-8")
    step = WorkspaceStep(
        name=StepEnum.DRC.value,
        directory=tmp_path / "drc_ecc",
        analysis={"qor_summary": summary_path},
        checklist={"path": tmp_path / "drc_ecc" / "checklist.json"},
    )

    assert refresh_step_checklist(workspace, step) is False
    item = step.checklist["checklist"][0]
    assert item["id"] == "quality.drc.clean"
    assert item["owner"] == "qor"
    assert item["blocked"] is True
    assert item["source"] == {
        "kind": "qor_gate",
        "path": "drc_ecc/analysis/qor_summary.json",
        "gate_id": "qor.drc.clean",
    }
