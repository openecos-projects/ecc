import json

from chipcompiler.data import (
    ChecklistState,
    EccAnalysis,
    EccFeature,
    EccStep,
    OriginDesign,
    Parameters,
    StateEnum,
    StepEnum,
    StepMetrics,
    Workspace,
    WorkspaceStep,
)
from chipcompiler.tools.ecc.metrics import _quality_gates, build_qor_summary_payload
from chipcompiler.tools.ecc.signoff_checklist import (
    _flow_items,
    _workspace_items,
    rebuild_home_checklist,
    refresh_step_checklist,
)


def _record(metric_id, value, path="feature/step.json"):
    return {
        "id": metric_id,
        "value": value,
        "source": {"kind": "feature", "path": path, "selector": f"/{metric_id}"},
    }


def test_quality_gates_only_include_final_drc_lvs_rcx_and_sta(tmp_path):
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

    lvs = WorkspaceStep(name=StepEnum.LVS.value, directory=tmp_path / "lvs_ecc")
    lvs_gates = _quality_gates(lvs, [_record("lvs_count", 0, "feature/lvs.step.json")])
    assert lvs_gates == [
        {
            "id": "qor.lvs.clean",
            "title": "Final LVS clean",
            "state": "pass",
            "blocking": True,
            "metrics": [
                {
                    "id": "lvs_count",
                    "actual": 0,
                    "operator": "==",
                    "expected": 0,
                    "source": _record("lvs_count", 0, "feature/lvs.step.json")["source"],
                }
            ],
            "evidence": [_record("lvs_count", 0, "feature/lvs.step.json")["source"]],
        }
    ]

    route = WorkspaceStep(name=StepEnum.ROUTING.value, directory=tmp_path / "route_ecc")
    assert (
        _quality_gates(
            route,
            [
                _record("route_dr_total_violation_count", 4),
                _record("route_la_total_overflow", 9),
            ],
        )
        == []
    )


def test_sta_quality_gates_require_all_corner_coverage_and_closure(tmp_path):
    feature_path = tmp_path / "sta_ecc" / "feature" / "sta.step.json"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text(
        json.dumps(
            {
                "sta": {
                    "signoff_metrics": {
                        "coverage": {"status": "pass"},
                        "setup": {"status": "blocked"},
                        "hold": {"status": "pass"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    step = EccStep(
        name=StepEnum.STA.value,
        directory=tmp_path / "sta_ecc",
        feature=EccFeature(step=feature_path),
    )
    gates = {
        gate["id"]: gate
        for gate in _quality_gates(
            step,
            [
                _record("sta_setup_wns", -0.01),
                _record("sta_setup_tns", -1),
                _record("sta_setup_violation_count", 1),
                _record("sta_hold_wns", 0.1),
                _record("sta_hold_tns", 0),
                _record("sta_hold_violation_count", 0),
            ],
        )
    }
    assert gates["qor.sta.setup_closed"]["state"] == "failed"
    assert gates["qor.sta.hold_closed"]["state"] == "pass"


def test_harden_mpc_area_gates_use_the_last_pre_route_success_db(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
        parameters=Parameters(
            data={
                "MPC": {
                    "core_template": {
                        "minimum_area": 100,
                        "maximum_area": 105,
                    }
                }
            }
        ),
    )
    workspace.flow.data = {
        "steps": [
            {"name": StepEnum.FLOORPLAN.value, "tool": "ecc", "state": StateEnum.Success.value},
            {"name": StepEnum.ROUTING.value, "tool": "ecc", "state": StateEnum.Success.value},
            {"name": StepEnum.DRC.value, "tool": "ecc", "state": StateEnum.Success.value},
        ]
    }
    route_db = tmp_path / "route_ecc" / "feature" / "route.db.json"
    route_db.parent.mkdir(parents=True)
    route_db.write_text(
        json.dumps({"Design Layout": {"die_area": 110}}),
        encoding="utf-8",
    )
    drc_db = tmp_path / "drc_ecc" / "feature" / "drc.db.json"
    drc_db.parent.mkdir(parents=True)
    drc_db.write_text(
        json.dumps({"Design Layout": {"die_area": 1}}),
        encoding="utf-8",
    )

    gates = {
        gate["id"]: gate
        for gate in _quality_gates(
            WorkspaceStep(name=StepEnum.HARDEN.value, directory=tmp_path / "Harden_ecc"),
            [],
            workspace,
        )
    }

    assert gates["qor.mpc.minimum_area"]["state"] == "pass"
    assert gates["qor.mpc.maximum_area"]["state"] == "failed"
    for gate in gates.values():
        assert gate["metrics"][0]["actual"] == 110
        assert gate["evidence"] == [
            {
                "kind": "feature",
                "path": "route_ecc/feature/route.db.json",
                "selector": "/Design Layout/die_area",
            }
        ]


def test_harden_mpc_area_gates_are_omitted_without_a_core_template(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        parameters=Parameters(data={"MPC": {}}),
    )

    assert (
        _quality_gates(
            WorkspaceStep(name=StepEnum.HARDEN.value, directory=tmp_path / "Harden_ecc"),
            [],
            workspace,
        )
        == []
    )


def test_harden_mpc_area_gates_are_unavailable_without_a_successful_physical_db(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        parameters=Parameters(
            data={
                "MPC": {
                    "core_template": {
                        "minimum_area": 100,
                        "maximum_area": 200,
                    }
                }
            }
        ),
    )
    workspace.flow.data = {
        "steps": [{"name": StepEnum.DRC.value, "tool": "ecc", "state": StateEnum.Success.value}]
    }

    gates = _quality_gates(
        WorkspaceStep(name=StepEnum.HARDEN.value, directory=tmp_path / "Harden_ecc"),
        [],
        workspace,
    )

    assert [gate["state"] for gate in gates] == ["unavailable", "unavailable"]


def test_harden_checklist_does_not_require_mpc_area_gates_without_mpc(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    (tmp_path / "home").mkdir()
    workspace.home.init(tmp_path / "home" / "home.json")
    workspace.home.set_checklist(tmp_path / "home" / "checklist.json")
    summary_path = tmp_path / "Harden_ecc" / "analysis" / "qor_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps({"schema_version": 4, "gates": []}),
        encoding="utf-8",
    )
    step = EccStep(
        name=StepEnum.HARDEN.value,
        directory=tmp_path / "Harden_ecc",
        analysis=EccAnalysis(qor_summary=summary_path),
        checklist=ChecklistState(path=tmp_path / "Harden_ecc" / "checklist.json"),
    )

    refresh_step_checklist(workspace, step)

    assert not any(item["id"].startswith("quality.mpc.") for item in step.checklist.checklist)


def test_harden_qor_summary_persists_mpc_area_gate_results(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
        parameters=Parameters(
            data={
                "MPC": {
                    "core_template": {
                        "minimum_area": 100,
                        "maximum_area": 105,
                    }
                }
            }
        ),
    )
    workspace.flow.data = {
        "steps": [{"name": StepEnum.ROUTING.value, "tool": "ecc", "state": StateEnum.Success.value}]
    }
    route_db = tmp_path / "route_ecc" / "feature" / "route.db.json"
    route_db.parent.mkdir(parents=True)
    route_db.write_text(
        json.dumps({"Design Layout": {"die_area": 110}}),
        encoding="utf-8",
    )

    summary = build_qor_summary_payload(
        workspace,
        WorkspaceStep(name=StepEnum.HARDEN.value, directory=tmp_path / "Harden_ecc"),
        StepMetrics(),
    )

    assert summary["quality_status"] == "blocked"
    assert {gate["id"]: gate["state"] for gate in summary["gates"]} == {
        "qor.mpc.minimum_area": "pass",
        "qor.mpc.maximum_area": "failed",
    }


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
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "gates": [
                    {
                        "id": "qor.drc.clean",
                        "title": "Final DRC clean",
                        "state": "failed",
                        "blocking": True,
                        "metrics": [
                            {"id": "drc_count", "actual": 2, "operator": "==", "expected": 0}
                        ],
                        "evidence": [{"kind": "feature", "path": "feature/drc.step.json"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    step = EccStep(
        name=StepEnum.DRC.value,
        directory=tmp_path / "drc_ecc",
        analysis=EccAnalysis(qor_summary=summary_path),
        checklist=ChecklistState(path=tmp_path / "drc_ecc" / "checklist.json"),
    )

    assert refresh_step_checklist(workspace, step) is False
    item = step.checklist.checklist[0]
    assert item["id"] == "quality.drc.clean"
    assert item["owner"] == "qor"
    assert item["blocked"] is True
    assert item["source"] == {
        "kind": "qor_gate",
        "path": "drc_ecc/analysis/qor_summary.json",
        "gate_id": "qor.drc.clean",
    }


def test_harden_checklist_blocks_on_failed_mpc_area_gate_and_keeps_route_evidence(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
        parameters=Parameters(data={"MPC": {"core_template": {}}}),
    )
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
    summary_path = tmp_path / "Harden_ecc" / "analysis" / "qor_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "gates": [
                    {
                        "id": "qor.mpc.minimum_area",
                        "title": "MPC minimum die area",
                        "state": "pass",
                        "metrics": [
                            {
                                "id": "minimum_area",
                                "actual": 110,
                                "operator": ">=",
                                "expected": 100,
                            }
                        ],
                        "evidence": [
                            {"kind": "feature", "path": "route_ecc/feature/route.db.json"}
                        ],
                    },
                    {
                        "id": "qor.mpc.maximum_area",
                        "title": "MPC maximum die area",
                        "state": "failed",
                        "metrics": [
                            {
                                "id": "maximum_area",
                                "actual": 110,
                                "operator": "<=",
                                "expected": 105,
                            }
                        ],
                        "evidence": [
                            {"kind": "feature", "path": "route_ecc/feature/route.db.json"}
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    step = EccStep(
        name=StepEnum.HARDEN.value,
        directory=tmp_path / "Harden_ecc",
        analysis=EccAnalysis(qor_summary=summary_path),
        checklist=ChecklistState(path=tmp_path / "Harden_ecc" / "checklist.json"),
    )

    assert refresh_step_checklist(workspace, step) is False
    items = {item["id"]: item for item in step.checklist.checklist}
    assert items["quality.mpc.minimum_area"]["blocked"] is False
    assert items["quality.mpc.maximum_area"]["blocked"] is True
    assert items["quality.mpc.maximum_area"]["evidence"] == [
        {"kind": "feature", "path": "route_ecc/feature/route.db.json"}
    ]


def _rtl_item(workspace):
    return next(
        item for item in _workspace_items(workspace) if item["id"] == "provenance.initial.rtl"
    )


def _passing_rtl_item(path):
    return {
        "id": "provenance.initial.rtl",
        "step": "workspace",
        "category": "provenance",
        "owner": "checklist",
        "policy": "block",
        "state": "pass",
        "blocked": False,
        "title": "Initial RTL",
        "summary": "Current output is present and non-empty.",
        "source": {"kind": "provenance", "path": path},
        "evidence": [{"kind": "provenance", "path": path}],
    }


def test_initial_rtl_prefers_configured_filelist_over_verilog_placeholder(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gcd.f").write_text("gcd.sv\n", encoding="utf-8")
    (origin / "gcd.sv").write_text("module gcd; endmodule\n", encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            # Workspace creation always sets origin_verilog, a placeholder
            # that never exists for filelist inputs.
            origin_verilog=origin / "gcd.v",
            input_filelist=origin / "gcd.f",
        ),
    )

    assert _rtl_item(workspace) == _passing_rtl_item("origin/gcd.f")


def test_initial_rtl_globs_filelist_when_attributes_missing(tmp_path):
    # load_workspace restores neither input_filelist nor .sv sources, so the
    # checklist must rediscover the filelist ahead of any RTL sources.
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gcd.f").write_text("gcd.sv\n", encoding="utf-8")
    (origin / "gcd.sv").write_text("module gcd; endmodule\n", encoding="utf-8")
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))

    assert _rtl_item(workspace) == _passing_rtl_item("origin/gcd.f")


def test_initial_rtl_globs_systemverilog_when_attributes_missing(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gcd.sv").write_text("module gcd; endmodule\n", encoding="utf-8")
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))

    assert _rtl_item(workspace) == _passing_rtl_item("origin/gcd.sv")


def test_initial_rtl_accepts_plain_verilog(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gcd.v").write_text("module gcd; endmodule\n", encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", origin_verilog=origin / "gcd.v"),
    )

    assert _rtl_item(workspace) == _passing_rtl_item("origin/gcd.v")


def test_initial_rtl_accepts_gzipped_verilog(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gcd.v.gz").write_bytes(b"\x1f\x8bfake")
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))

    assert _rtl_item(workspace) == _passing_rtl_item("origin/gcd.v.gz")


def test_initial_rtl_reports_configured_file_missing(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            origin_verilog=origin / "gcd.v",
            input_filelist=origin / "gcd.f",
        ),
    )

    assert _rtl_item(workspace) == {
        "id": "provenance.initial.rtl",
        "step": "workspace",
        "category": "provenance",
        "owner": "checklist",
        "policy": "block",
        "state": "failed",
        "blocked": True,
        "title": "Initial RTL",
        "summary": "Required file is missing.",
        "source": {"kind": "provenance", "path": "origin/gcd.f"},
        "evidence": [{"kind": "provenance", "path": "origin/gcd.f"}],
    }


def test_home_checklist_flow_completed_tracks_final_harden_state(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    (tmp_path / "home").mkdir()
    workspace.home.init(tmp_path / "home" / "home.json")
    workspace.home.set_checklist(tmp_path / "home" / "checklist.json")
    workspace.flow.path = tmp_path / "home" / "flow.json"
    workspace.flow.data = {
        "steps": [
            {"name": step.value, "tool": "ecc", "state": StateEnum.Success.value}
            for step in (
                StepEnum.ROUTING,
                StepEnum.DRC,
                StepEnum.LVS,
                StepEnum.FILLER,
                StepEnum.POST_ROUTE_LEC,
                StepEnum.RCX,
                StepEnum.STA,
            )
        ]
        + [{"name": StepEnum.HARDEN.value, "tool": "ecc", "state": StateEnum.Ongoing.value}]
    }
    workspace.flow.data["steps"][-3]["tool"] = "yosys_lec"
    step = EccStep(
        name=StepEnum.HARDEN.value,
        directory=tmp_path / "Harden_ecc",
        checklist=ChecklistState(path=tmp_path / "Harden_ecc" / "checklist.json"),
    )

    refresh_step_checklist(workspace, step)
    home_items = {
        item["id"]: item
        for item in json.loads((tmp_path / "home" / "checklist.json").read_text(encoding="utf-8"))[
            "checklist"
        ]
    }
    assert home_items["flow.harden.completed"]["state"] == "failed"
    assert "Ongoing" in home_items["flow.harden.completed"]["summary"]

    workspace.flow.data["steps"][-1]["state"] = StateEnum.Success.value
    rebuild_home_checklist(workspace)
    home_items = {
        item["id"]: item
        for item in json.loads((tmp_path / "home" / "checklist.json").read_text(encoding="utf-8"))[
            "checklist"
        ]
    }
    assert home_items["flow.harden.completed"]["state"] == "pass"
    assert home_items["flow.harden.completed"]["blocked"] is False
    assert home_items["flow.harden.completed"]["summary"] == (
        "Required flow stage completed successfully."
    )


def test_home_checklist_uses_origin_golden_when_flow_has_no_synthesis(tmp_path):
    origin = tmp_path / "origin" / "gcd.v"
    origin.parent.mkdir()
    origin.write_text("module gcd; imported mapped netlist\nendmodule\n", encoding="utf-8")
    leftover = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v.gz"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("module gcd; leftover synthesis\nendmodule\n", encoding="utf-8")
    filler = tmp_path / "filler_ecc" / "output" / "gcd_filler.v.gz"
    filler.parent.mkdir(parents=True)
    filler.write_text("module gcd; filler\nendmodule\n", encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", origin_verilog=origin),
    )
    workspace.flow.data = {
        "steps": [
            {"name": step.value, "tool": "ecc", "state": StateEnum.Success.value}
            for step in (
                StepEnum.NETLIST_OPT,
                StepEnum.ROUTING,
                StepEnum.DRC,
                StepEnum.LVS,
                StepEnum.FILLER,
                StepEnum.POST_ROUTE_LEC,
                StepEnum.RCX,
                StepEnum.STA,
                StepEnum.HARDEN,
            )
        ]
    }
    workspace.flow.data["steps"][5]["tool"] = "yosys_lec"

    items = {item["id"]: item for item in _flow_items(workspace)}
    assert "flow.postroutelec.completed" in items
    assert items["flow.postroutelec.completed"]["state"] == "pass"


def test_home_checklist_ignores_leftover_synthesis_dir_without_synthesis_step(tmp_path):
    leftover = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.v.gz"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("module gcd; leftover synthesis\nendmodule\n", encoding="utf-8")
    filler = tmp_path / "filler_ecc" / "output" / "gcd_filler.v.gz"
    filler.parent.mkdir(parents=True)
    filler.write_text("module gcd; filler\nendmodule\n", encoding="utf-8")
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    workspace.flow.data = {
        "steps": [
            {"name": step.value, "tool": "ecc", "state": StateEnum.Success.value}
            for step in (
                StepEnum.NETLIST_OPT,
                StepEnum.FILLER,
                StepEnum.HARDEN,
            )
        ]
    }

    items = {item["id"]: item for item in _flow_items(workspace)}
    assert leftover.is_file()
    assert "flow.postroutelec.completed" not in items
