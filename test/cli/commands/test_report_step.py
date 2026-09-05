import json
import os

from chipcompiler.cli import main as cli_main

FLOORPLAN_STEP_JSON = {
    "run": {"state": "Success", "runtime_seconds": 1.757, "peak_memory_mb": 143.227},
    "constraints": {"sdc": {"availability": "available", "sha256": "abc123", "size_bytes": 253}},
}

FLOORPLAN_DB_JSON = {
    "Design Information": {"design_name": "gcd", "eda_tool": "ecc"},
    "Design Statis": {"num_instances": 454, "num_nets": 368},
}

FLOORPLAN_QOR_METRICS = {
    "schema_version": 3,
    "analysis_revision": "quality-gates-v4",
    "tool": "ecc",
    "step": "Floorplan",
    "design": "gcd",
    "status": "success",
    "metrics": [
        {
            "id": "core_area",
            "display_name": "Core Area",
            "value": 1971.2,
            "unit": "um^2",
            "category": "area_cost",
            "direction": "lower_is_better",
            "project_role": "trend",
            "rating": {"gate": False, "score": True, "trend": True},
            "source": {
                "kind": "feature",
                "path": "feature/Floorplan.db.json",
                "selector": "/Design Layout/core_area",
            },
        },
        {
            "id": "num_instances",
            "display_name": "Instance Count",
            "value": 454,
            "unit": "count",
            "category": "area_cost",
            "direction": "lower_is_better",
            "project_role": "trend",
            "rating": {"gate": False, "score": True, "trend": True},
            "source": {
                "kind": "feature",
                "path": "feature/Floorplan.db.json",
                "selector": "/Design Statis/num_instances",
            },
        },
    ],
}

FLOORPLAN_QOR_SUMMARY = {
    "schema_version": 4,
    "analysis_revision": "quality-gates-v4",
    "tool": "ecc",
    "step": "Floorplan",
    "design": "gcd",
    "analysis_status": "valid",
    "quality_status": "pass",
    "metric_count": 2,
    "dimensions": {"area_cost": {"metric_count": 2}},
    "gates": [],
    "missing_metrics": [],
    "metrics_file": "qor_metrics.json",
}

FLOORPLAN_CHECKLIST = {
    "schema_version": 3,
    "kind": "signoff_checklist",
    "checker_revision": "signoff-v1",
    "generated_at": "2026-09-03T14:55:19.720359Z",
    "status": "ready",
    "summary": {"passed": 1, "blocked": 0, "attention": 0, "unavailable": 0},
    "checklist": [
        {
            "id": "artifact.floorplan.def",
            "step": "Floorplan",
            "category": "artifact",
            "owner": "checklist",
            "policy": "block",
            "state": "pass",
            "blocked": False,
            "title": "Floorplan DEF",
            "summary": "Current output is present and non-empty.",
            "source": {"kind": "output", "path": "Floorplan_ecc/output/gcd_Floorplan.def.gz"},
            "evidence": [{"kind": "output", "path": "Floorplan_ecc/output/gcd_Floorplan.def.gz"}],
        }
    ],
}

DRC_QOR_SUMMARY = {
    "schema_version": 4,
    "analysis_revision": "quality-gates-v4",
    "tool": "ecc",
    "step": "drc",
    "design": "gcd",
    "analysis_status": "valid",
    "quality_status": "blocked",
    "metric_count": 1,
    "dimensions": {},
    "gates": [
        {
            "id": "qor.drc.clean",
            "title": "Final DRC clean",
            "state": "failed",
            "blocking": True,
            "metrics": [{"id": "drc_count", "actual": 336, "operator": "==", "expected": 0}],
            "evidence": [],
        }
    ],
    "missing_metrics": [],
    "metrics_file": "qor_metrics.json",
}

DRC_CHECKLIST = {
    "schema_version": 3,
    "kind": "signoff_checklist",
    "checker_revision": "signoff-v1",
    "generated_at": "2026-09-03T14:55:19.720359Z",
    "status": "blocked",
    "summary": {"passed": 0, "blocked": 1, "attention": 0, "unavailable": 0},
    "checklist": [
        {
            "id": "quality.drc.clean",
            "step": "drc",
            "category": "quality_gate",
            "owner": "qor",
            "policy": "block",
            "state": "failed",
            "blocked": True,
            "title": "Final DRC clean",
            "summary": "drc_count=336 (required == 0)",
            "source": {
                "kind": "qor_gate",
                "path": "drc_ecc/analysis/qor_summary.json",
                "gate_id": "qor.drc.clean",
            },
            "evidence": [],
        }
    ],
}

FLOW_STEPS = [
    {
        "name": "Floorplan",
        "tool": "ecc",
        "state": "Success",
        "runtime": "0:0:1",
        "peak memory (mb)": 143.227,
    },
    {
        "name": "Timing optimization",
        "tool": "sizer",
        "state": "Success",
        "runtime": "0:0:9",
        "peak memory (mb)": 2.305,
    },
]


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def create_step_workspace(tmp_path, *, with_drc=True, with_home_checklist=False):
    """Minimal completed-workspace fixture shaped like a real run output."""
    ws = str(tmp_path / "ws")
    _write(os.path.join(ws, "home", "flow.json"), {"steps": FLOW_STEPS})

    floorplan_dir = os.path.join(ws, "Floorplan_ecc")
    _write(os.path.join(floorplan_dir, "feature", "Floorplan.step.json"), FLOORPLAN_STEP_JSON)
    _write(os.path.join(floorplan_dir, "feature", "Floorplan.db.json"), FLOORPLAN_DB_JSON)
    _write(os.path.join(floorplan_dir, "analysis", "qor_metrics.json"), FLOORPLAN_QOR_METRICS)
    _write(os.path.join(floorplan_dir, "analysis", "qor_summary.json"), FLOORPLAN_QOR_SUMMARY)
    _write(os.path.join(floorplan_dir, "checklist.json"), FLOORPLAN_CHECKLIST)

    sizer_dir = os.path.join(ws, "timing_optimization_sizer")
    _write(
        os.path.join(sizer_dir, "feature", "Timing optimization.step.json"),
        {"run": {"state": "Success", "runtime_seconds": 9.151, "peak_memory_mb": 2.305}},
    )

    if with_drc:
        drc_dir = os.path.join(ws, "drc_ecc")
        _write(
            os.path.join(drc_dir, "analysis", "qor_metrics.json"),
            {
                "schema_version": 3,
                "metrics": [
                    {
                        "id": "drc_count",
                        "display_name": "DRC Count",
                        "value": 336,
                        "unit": "count",
                        "category": "clock_robustness_dfm",
                        "direction": "lower_is_better",
                        "project_role": "gate",
                        "rating": {"gate": True, "score": True, "trend": False},
                        "source": {
                            "kind": "feature",
                            "path": "feature/drc.step.json",
                            "selector": "/drc/number",
                        },
                    }
                ],
            },
        )
        _write(os.path.join(drc_dir, "analysis", "qor_summary.json"), DRC_QOR_SUMMARY)
        _write(os.path.join(drc_dir, "checklist.json"), DRC_CHECKLIST)

    if with_home_checklist:
        _write(
            os.path.join(ws, "home", "checklist.json"),
            {
                "schema_version": 3,
                "kind": "signoff_checklist",
                "status": "blocked",
                "summary": {"passed": 0, "blocked": 99, "attention": 0, "unavailable": 0},
                "checklist": [
                    FLOORPLAN_CHECKLIST["checklist"][0],
                    DRC_CHECKLIST["checklist"][0],
                    {
                        "id": "flow.workspace.completed",
                        "step": "workspace",
                        "category": "flow",
                        "policy": "block",
                        "state": "pass",
                        "blocked": False,
                        "title": "Flow completed",
                        "summary": "",
                    },
                ],
            },
        )
    return ws


def run_step(args, capsys):
    rc = cli_main.run(args)
    return rc, json.loads(capsys.readouterr().out)


def step_args(tmp_path, *args, workspace="ws"):
    """`report step` argv selecting a managed workspace of tmp_path."""
    return ["report", "step", "--project", str(tmp_path), "--workspace", workspace, *args]


class TestStepOverview:
    def test_overview_includes_every_rtl2gds_step(self, tmp_path, capsys):
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        ws = str(tmp_path / "ws")
        _write(
            os.path.join(ws, "home", "flow.json"),
            {
                "steps": [
                    {"name": step.value, "tool": tool, "state": state.value}
                    for step, tool, state in build_rtl2gds_flow()
                ]
            },
        )

        rc, data = run_step(step_args(tmp_path, "--json"), capsys)

        assert rc == 0
        assert [record["step"] for record in data["records"][1:]] == [
            "synthesis",
            "lec",
            "floorplan",
            "placement",
            "cts",
            "legalization",
            "timing_optimization",
            "routing",
            "filler",
            "rcx",
            "sta",
            "lvs",
            "postroutelec",
            "drc",
            "harden",
        ]

    def test_overview_records(self, tmp_path, capsys):
        ws = create_step_workspace(tmp_path)

        rc, data = run_step(step_args(tmp_path, "--json"), capsys)

        assert rc == 0
        assert data["records"] == [
            {
                "report": "step",
                "view": "overview",
                "workspace": ws,
                "steps": 3,
                "inspect": f"ecc report step <step> --project {tmp_path} --workspace ws",
            },
            {
                "step": "floorplan",
                "tool": "ecc",
                "status": "success",
                "runtime": "0:0:1",
                "peak_memory_mb": 143.227,
                "metrics": 2,
                "quality": "pass",
                "checklist": "ready",
                "blocked": 0,
                "inspect": f"ecc report step floorplan --project {tmp_path} --workspace ws",
            },
            {
                "step": "timing_optimization",
                "tool": "sizer",
                "status": "success",
                "runtime": "0:0:9",
                "peak_memory_mb": 2.305,
                "metrics": None,
                "quality": None,
                "checklist": None,
                "blocked": 0,
                "inspect": (
                    f"ecc report step timing_optimization --project {tmp_path} --workspace ws"
                ),
            },
            {
                "step": "drc",
                "tool": "ecc",
                "status": "unknown",
                "runtime": None,
                "peak_memory_mb": None,
                "metrics": 1,
                "quality": "blocked",
                "checklist": "blocked",
                "blocked": 1,
                "inspect": f"ecc report step drc --project {tmp_path} --workspace ws",
            },
        ]

    def test_overview_without_steps(self, tmp_path, capsys):
        ws = str(tmp_path / "empty")
        os.makedirs(ws)

        rc, data = run_step(step_args(tmp_path, "--json", workspace="empty"), capsys)

        assert rc == 0
        assert data["records"] == [
            {
                "report": "step",
                "view": "overview",
                "workspace": ws,
                "steps": 0,
                "inspect": f"ecc report step <step> --project {tmp_path} --workspace empty",
                "step_status": "no_steps",
                "run": f"ecc run --project {tmp_path} --workspace empty",
            }
        ]

    def test_overview_text(self, tmp_path, capsys):
        create_step_workspace(tmp_path)

        rc = cli_main.run(step_args(tmp_path))
        out = capsys.readouterr().out

        assert rc == 0
        assert "peak MB" in out
        assert "143.227" in out
        assert "floorplan" in out
        assert "timing_optimization" in out
        assert "blocked (1 blocked)" in out


class TestStepDetail:
    def test_detail_feature_section(self, tmp_path, capsys):
        create_step_workspace(tmp_path)

        rc, data = run_step(
            step_args(tmp_path, "floorplan", "--section", "feature", "--json"), capsys
        )

        assert rc == 0
        head, *section = data["records"]
        assert head["view"] == "detail"
        assert head["step"] == "floorplan"
        assert head["step_name"] == "Floorplan"
        assert head["sections"] == ["feature"]
        assert section == [
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "run",
                "key": "run.peak_memory_mb",
                "value": 143.227,
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "run",
                "key": "run.runtime_seconds",
                "value": 1.757,
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "run",
                "key": "run.state",
                "value": "Success",
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "constraint",
                "key": "constraints.sdc.availability",
                "value": "available",
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "constraint",
                "key": "constraints.sdc.sha256",
                "value": "abc123",
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "constraint",
                "key": "constraints.sdc.size_bytes",
                "value": 253,
                "source": "Floorplan_ecc/feature/Floorplan.step.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "stat",
                "key": "Design Information.design_name",
                "value": "gcd",
                "source": "Floorplan_ecc/feature/Floorplan.db.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "stat",
                "key": "Design Information.eda_tool",
                "value": "ecc",
                "source": "Floorplan_ecc/feature/Floorplan.db.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "stat",
                "key": "Design Statis.num_instances",
                "value": 454,
                "source": "Floorplan_ecc/feature/Floorplan.db.json",
            },
            {
                "step": "floorplan",
                "section": "feature",
                "kind": "stat",
                "key": "Design Statis.num_nets",
                "value": 368,
                "source": "Floorplan_ecc/feature/Floorplan.db.json",
            },
        ]

    def test_detail_analysis_section_with_gate(self, tmp_path, capsys):
        create_step_workspace(tmp_path)

        rc, data = run_step(
            step_args(tmp_path, "drc", "--section", "analysis", "--json"), capsys
        )

        assert rc == 0
        head, summary, metric, gate = data["records"]
        assert head["sections"] == ["analysis"]
        assert summary == {
            "step": "drc",
            "section": "analysis",
            "kind": "summary",
            "quality_status": "blocked",
            "analysis_status": "valid",
            "metric_count": 1,
            "dimensions": {},
            "missing_metrics": [],
            "analysis_revision": "quality-gates-v4",
        }
        assert metric == {
            "step": "drc",
            "section": "analysis",
            "kind": "metric",
            "metric": "drc_count",
            "label": "DRC Count",
            "value": 336,
            "unit": "count",
            "category": "clock_robustness_dfm",
            "direction": "lower_is_better",
            "role": "gate",
            "gate": True,
            "score": True,
            "source": "drc_ecc/feature/drc.step.json#/drc/number",
        }
        assert gate == {
            "step": "drc",
            "section": "analysis",
            "kind": "gate",
            "gate": "qor.drc.clean",
            "title": "Final DRC clean",
            "state": "failed",
            "blocking": True,
            "checks": [{"metric": "drc_count", "actual": 336, "operator": "==", "expected": 0}],
        }

    def test_detail_checklist_from_step_file(self, tmp_path, capsys):
        create_step_workspace(tmp_path)

        rc, data = run_step(
            step_args(tmp_path, "floorplan", "--section", "checklist", "--json"), capsys
        )

        assert rc == 0
        head, summary, item = data["records"]
        assert summary == {
            "step": "floorplan",
            "section": "checklist",
            "kind": "summary",
            "checklist_status": "ready",
            "source": "step",
            "passed": 1,
            "blocked": 0,
            "attention": 0,
            "unavailable": 0,
        }
        assert item == {
            "step": "floorplan",
            "section": "checklist",
            "kind": "item",
            "id": "artifact.floorplan.def",
            "category": "artifact",
            "title": "Floorplan DEF",
            "state": "pass",
            "policy": "block",
            "blocked": False,
            "summary": "Current output is present and non-empty.",
            "evidence": ["Floorplan_ecc/output/gcd_Floorplan.def.gz"],
        }

    def test_detail_checklist_falls_back_to_home(self, tmp_path, capsys):
        ws = create_step_workspace(tmp_path, with_home_checklist=True)
        os.remove(os.path.join(ws, "Floorplan_ecc", "checklist.json"))

        rc, data = run_step(
            step_args(tmp_path, "floorplan", "--section", "checklist", "--json"), capsys
        )

        assert rc == 0
        head, summary, item = data["records"]
        assert summary["source"] == "home"
        assert summary["passed"] == 1
        assert summary["blocked"] == 0
        assert item["id"] == "artifact.floorplan.def"

    def test_detail_unavailable_sections(self, tmp_path, capsys):
        create_step_workspace(tmp_path, with_drc=False)

        rc, data = run_step(step_args(tmp_path, "timing_optimization", "--json"), capsys)

        assert rc == 0
        statuses = {
            r["section"]: r["section_status"] for r in data["records"] if "section_status" in r
        }
        # The sizer step has run facts but no analysis or checklist outputs.
        assert statuses == {"analysis": "unavailable", "checklist": "unavailable"}
        feature_keys = [r["key"] for r in data["records"] if r.get("section") == "feature"]
        assert feature_keys == [
            "run.peak_memory_mb",
            "run.runtime_seconds",
            "run.state",
        ]

    def test_detail_accepts_flow_token_with_spaces(self, tmp_path, capsys):
        create_step_workspace(tmp_path, with_drc=False)

        rc, data = run_step(step_args(tmp_path, "timing optimization", "--json"), capsys)

        assert rc == 0
        assert data["records"][0]["step"] == "timing_optimization"

    def test_detail_text(self, tmp_path, capsys):
        create_step_workspace(tmp_path)

        rc = cli_main.run(step_args(tmp_path, "drc"))
        out = capsys.readouterr().out

        assert rc == 0
        assert "[BLOCK] qor.drc.clean — drc_count=336 == 0" in out
        assert "[failed] Final DRC clean — drc_count=336 (required == 0)" in out


class TestStepErrors:
    def test_unknown_step(self, tmp_path, capsys):
        create_step_workspace(tmp_path, with_drc=False)

        rc, data = run_step(step_args(tmp_path, "nope", "--json"), capsys)

        assert rc == 1
        assert data["records"] == [
            {
                "kind": "error",
                "error": "unknown_step",
                "step": "nope",
                "available": ["floorplan", "timing_optimization"],
                "inspect": f"ecc report step --project {tmp_path} --workspace ws",
            }
        ]

    def test_invalid_section(self, tmp_path, capsys):
        create_step_workspace(tmp_path, with_drc=False)

        rc, data = run_step(
            step_args(tmp_path, "floorplan", "--section", "bogus", "--json"), capsys
        )

        assert rc == 1
        assert data["records"][0]["error"] == "invalid_section"
        assert data["records"][0]["sections"] == ["feature", "analysis", "checklist"]

    def test_section_requires_step(self, tmp_path, capsys):
        create_step_workspace(tmp_path, with_drc=False)

        rc, data = run_step(step_args(tmp_path, "--section", "analysis", "--json"), capsys)

        assert rc == 1
        assert data["records"][0]["error"] == "section_requires_step"

    def test_missing_workspace_directory(self, tmp_path, capsys):
        rc, data = run_step(step_args(tmp_path, "--json", workspace="absent"), capsys)

        assert rc == 1
        assert data["records"][0]["error"] == "missing_workspace"
        assert data["records"][0]["workspace"] == str(tmp_path / "absent")


class TestStepReadOnly:
    def test_invocation_writes_nothing(self, tmp_path, capsys):
        ws = create_step_workspace(tmp_path)

        def snapshot():
            return sorted(
                os.path.join(root, name) for root, _dirs, files in os.walk(ws) for name in files
            )

        before = snapshot()
        cli_main.run(step_args(tmp_path))
        cli_main.run(step_args(tmp_path, "floorplan", "--json"))

        assert snapshot() == before
