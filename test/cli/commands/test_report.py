import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main


@pytest.fixture
def report_mocks(monkeypatch):
    """Stub workspace resolution and both report builders."""
    workspace = SimpleNamespace(
        directory="/tmp/ws",
        name="gcd",
        design=SimpleNamespace(name="gcd"),
        flow=SimpleNamespace(data={}),
        config={},
    )
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)

    from chipcompiler.engine.qor_report import QorDimensionScore, QorScoreReport

    qor_report = QorScoreReport(
        workspace="/tmp/ws",
        design="gcd",
        overall_score=72.5,
        status="Green",
        gate_status="pass",
        area_scoring_step="Harden",
        dimension_scores=[
            QorDimensionScore("timing", "Timing", 0.35, 80.0, 2),
        ],
    )

    from chipcompiler.engine.signoff.report_checklist import (
        ChecklistItemView,
        ChecklistReport,
    )

    checklist_report = ChecklistReport(
        available=True,
        workspace="/tmp/ws",
        status="attention",
        generated_at="2026-01-01T00:00:00Z",
        items=[
            ChecklistItemView(
                id="q.drc",
                step="drc",
                category="quality",
                title="DRC clean",
                state="failed",
                policy="block",
                blocked=True,
                summary="drc_count=2",
            ),
            ChecklistItemView(
                id="a.gds",
                step="Harden",
                category="artifact",
                title="Harden GDS",
                state="warning",
                policy="warn",
                blocked=False,
                summary="missing",
            ),
        ],
        summary={"passed": 1, "blocked": 1, "attention": 1, "unavailable": 0},
    )
    # ChecklistReport.summary is a field default; set explicitly
    checklist_report.summary = {"passed": 1, "blocked": 1, "attention": 1, "unavailable": 0}

    from chipcompiler.engine import qor_report as qor_module
    from chipcompiler.engine.signoff import report_checklist as checklist_module

    monkeypatch.setattr(qor_module, "build_qor_report", lambda ws: qor_report)
    monkeypatch.setattr(qor_module, "generate_qor_report", lambda ws: "QOR BODY")
    monkeypatch.setattr(checklist_module, "build_checklist_report", lambda ws: checklist_report)
    monkeypatch.setattr(checklist_module, "generate_checklist_report", lambda ws: "CHECKLIST BODY")
    return SimpleNamespace(workspace=workspace, qor=qor_report, checklist=checklist_report)


class TestReportQor:
    def test_qor_writes_default_destination(
        self, tmp_path, capsys, monkeypatch, create_cli_project, report_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir)
        report_mocks.workspace.directory = run_dir

        rc = cli_main.run(["report", "qor", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        record = data["records"][0]
        assert record["report"] == "qor"
        assert record["status"] == "written"
        assert record["overall_score"] == 72.5
        assert record["dimensions"][0]["dimension"] == "Timing"
        expected = os.path.join(run_dir, "signoff", "gcd_qor_report.txt")
        assert record["path"] == expected
        with open(expected) as f:
            assert f.read() == "QOR BODY"

    def test_qor_output_override(
        self, tmp_path, capsys, monkeypatch, create_cli_project, report_mocks
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        override = str(tmp_path / "qor.txt")

        rc = cli_main.run(["report", "qor", "-o", override, "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"][0]["path"] == override
        assert os.path.isfile(override)

    def test_qor_with_workspace_flag(self, tmp_path, capsys, monkeypatch, report_mocks):
        rc = cli_main.run(["report", "qor", "--workspace", str(tmp_path / "ws"), "--plain"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "report=qor" in out
        assert os.path.isfile(os.path.join(str(tmp_path / "ws"), "signoff", "gcd_qor_report.txt"))


class TestReportChecklist:
    def test_checklist_records_summary(
        self, tmp_path, capsys, monkeypatch, create_cli_project, report_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir)
        report_mocks.workspace.directory = run_dir

        rc = cli_main.run(["report", "checklist", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        record = data["records"][0]
        assert record["report"] == "checklist"
        assert record["status"] == "written"
        assert record["checklist_status"] == "attention"
        assert record["blocked"] == 1
        assert record["attention"] == 1
        assert record["items"] == 2
        expected = os.path.join(run_dir, "signoff", "checklist_report.txt")
        assert record["path"] == expected
        with open(expected) as f:
            assert f.read() == "CHECKLIST BODY"

    def test_checklist_unavailable_maps_to_error(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        from types import SimpleNamespace as NS

        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: NS(
                directory="/tmp/x", name="g", flow=NS(data={}), design=NS(name="g"), config={}
            ),
        )
        from chipcompiler.engine.signoff import report_checklist as checklist_module

        monkeypatch.setattr(
            checklist_module,
            "build_checklist_report",
            lambda ws: checklist_module.ChecklistReport(available=False, workspace="/tmp/x"),
        )
        monkeypatch.setattr(checklist_module, "generate_checklist_report", lambda ws: "UNAVAILABLE")

        rc = cli_main.run(["report", "checklist", "--project", project_dir, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "checklist_unavailable"


class TestReportWorkspaceResolution:
    def test_workspace_conflicts_with_project(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("conflicts must be rejected before workspace load"),
        )

        rc = cli_main.run(["report", "qor", "--project", "p", "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "project_workspace_conflict"

    def test_missing_run_workspace(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()  # no runs/default

        rc = cli_main.run(["report", "qor", "--project", project_dir, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "missing_workspace"
