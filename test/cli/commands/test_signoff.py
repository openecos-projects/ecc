import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main


@pytest.fixture
def workspace_stub(monkeypatch):
    """Patch workspace resolution and engine/runtime calls for signoff tests."""
    seen = SimpleNamespace(
        load_path=None,
        inspect=None,
        export=None,
    )
    workspace = SimpleNamespace(
        directory="/tmp/ws",
        name="gcd",
        design=SimpleNamespace(name="gcd"),
        flow=SimpleNamespace(data={}),
        config={},
    )

    def fake_load_workspace(path):
        seen.load_path = path
        return workspace

    monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
    return SimpleNamespace(seen=seen, workspace=workspace)


REVIEW = {
    "status": "attention",
    "groups": [
        {
            "id": "harden",
            "label": "Harden",
            "status": "ready",
            "available": 4,
            "expected": 4,
            "summary": {},
        },
        {
            "id": "sta",
            "label": "STA",
            "status": "attention",
            "available": 2,
            "expected": 3,
            "summary": {},
        },
    ],
    "risks": [
        {
            "severity": "warning",
            "title": "STA report missing",
            "summary": "one corner lacks reports",
            "details": [{"location": "sta_ecc/report/MAX_125", "reason": "file missing"}],
        },
    ],
}


def _patch_inspect(monkeypatch, review=REVIEW):
    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.inspect_signoff_package",
        lambda workspace: review,
    )


def _patch_export(monkeypatch, destination="/tmp/pkg.tar.gz", error=None):
    calls = []

    def fake_export(workspace, output_path, additional_files=None, *, include_debug=False):
        calls.append(
            {
                "workspace": workspace,
                "output_path": output_path,
                "additional_files": additional_files,
                "include_debug": include_debug,
            }
        )
        if error is not None:
            raise error
        return destination

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.export_signoff_package_archive", fake_export
    )
    return calls


class TestSignoffInspect:
    def test_inspect_payload(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir)
        _patch_inspect(monkeypatch)

        rc = cli_main.run(["signoff", "inspect", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        summary = data["records"][0]
        assert summary["signoff"] == "inspect"
        assert summary["status"] == "attention"
        groups = [r for r in data["records"] if "group" in r]
        assert [g["group"] for g in groups] == ["harden", "sta"]
        risks = [r for r in data["records"] if "risk" in r]
        assert risks[0]["title"] == "STA report missing"

    def test_inspect_blocked_still_exits_zero(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        _patch_inspect(monkeypatch, {"status": "blocked", "groups": [], "risks": []})

        rc = cli_main.run(["signoff", "inspect", "--project", project_dir, "--json"])

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["records"][0]["status"] == "blocked"

    def test_inspect_text_rendering(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        _patch_inspect(monkeypatch)

        rc = cli_main.run(["signoff", "inspect", "--project", project_dir])

        out = capsys.readouterr().out
        assert rc == 0
        assert "[signoff]" in out
        assert "harden" in out
        assert "STA report missing" in out

    def test_inspect_with_workspace_flag(self, tmp_path, capsys, monkeypatch, workspace_stub):
        _patch_inspect(monkeypatch)
        os.makedirs(tmp_path / "ws")

        rc = cli_main.run(["signoff", "inspect", "--workspace", str(tmp_path / "ws"), "--json"])

        assert rc == 0
        assert workspace_stub.seen.load_path == str(tmp_path / "ws")

    def test_workspace_conflicts_with_project(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("conflicts must be rejected before workspace load"),
        )

        rc = cli_main.run(["signoff", "inspect", "--project", "p", "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "project_workspace_conflict"

    def test_missing_run_workspace(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()  # no runs/default directory

        rc = cli_main.run(["signoff", "inspect", "--project", project_dir, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "missing_workspace"


class TestSignoffExport:
    def test_export_records_path(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        calls = _patch_export(monkeypatch, destination="/tmp/out/pkg.tar.gz")

        rc = cli_main.run(
            ["signoff", "export", "-o", "/tmp/out/pkg.tar.gz", "--project", project_dir, "--json"]
        )

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"][0] == {
            "signoff": "export",
            "status": "exported",
            "path": "/tmp/out/pkg.tar.gz",
            "inspect_cmd": f"ecc signoff inspect --project {project_dir}",
        }
        assert calls[0]["output_path"] == "/tmp/out/pkg.tar.gz"
        assert calls[0]["include_debug"] is False

    def test_export_forwards_include_debug(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        calls = _patch_export(monkeypatch)

        rc = cli_main.run(
            [
                "signoff",
                "export",
                "-o",
                "/tmp/pkg.tar.gz",
                "--include-debug",
                "--project",
                project_dir,
                "--json",
            ]
        )

        assert rc == 0
        assert calls[0]["include_debug"] is True

    def test_export_incomplete_maps_to_error(
        self, tmp_path, capsys, monkeypatch, create_cli_project, workspace_stub
    ):
        from chipcompiler.runtime.workspace_api import RuntimeApiError

        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"))
        _patch_export(
            monkeypatch,
            error=RuntimeApiError("command_failed", "signoff package is incomplete: x"),
        )

        rc = cli_main.run(
            ["signoff", "export", "-o", "/tmp/pkg.tar.gz", "--project", project_dir, "--json"]
        )

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "signoff_incomplete"
        assert "incomplete" in record["reason"]
