"""--workspace resolution shared by the read-only status/log/config commands."""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main


def _make_workspace(tmp_path, name="ws"):
    ws = str(tmp_path / name)
    os.makedirs(ws)
    return ws


class TestWorkspaceConflict:
    def test_status_conflicts_with_project(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("read-only commands must not load a workspace"),
        )

        rc = cli_main.run(["status", "--project", "p", "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "project_workspace_conflict"

    def test_log_conflicts_with_run_id(self, tmp_path, capsys):
        rc = cli_main.run(["log", "--run-id", "r", "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "project_workspace_conflict"

    def test_config_conflicts_with_project(self, tmp_path, capsys):
        rc = cli_main.run(["config", "--project", "p", "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "project_workspace_conflict"


class TestInvalidWorkspace:
    @pytest.mark.parametrize("command", (["status"], ["log"], ["config"]))
    def test_absent_directory_is_invalid(self, tmp_path, capsys, command):
        absent = str(tmp_path / "absent")

        rc = cli_main.run([*command, "--workspace", absent, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "invalid_workspace"
        assert record["workspace"] == absent


class TestWorkspaceViews:
    def test_status_reads_flow_json(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_step_dir

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_step_dir(ws, "CTS", "ecc")

        rc = cli_main.run(["status", "--workspace", ws, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"][0]["workspace"] == ws
        assert data["records"][0]["run"] == "ws"
        assert any(r.get("step") == "cts" for r in data["records"][1:])

    def test_log_reads_step_log(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_step_dir

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_step_dir(
            ws,
            "Synthesis",
            "yosys",
            subdirs=["log"],
            files={"log/synthesis.log": "Error: bad thing\n"},
        )

        rc = cli_main.run(["log", "synthesis", "--workspace", ws, "--json"])

        records = json.loads(capsys.readouterr().out)["records"]
        assert rc == 0
        assert any("bad thing" in r.get("line", "") for r in records)

    def test_config_step_view(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_cts_workspace_config

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_cts_workspace_config(ws)

        rc = cli_main.run(["config", "cts", "--workspace", ws, "--json"])

        records = json.loads(capsys.readouterr().out)["records"]
        assert rc == 0
        assert any(r.get("step") == "cts" for r in records)


class TestReadOnly:
    def test_invocation_writes_nothing(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_step_dir

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_step_dir(
            ws,
            "Synthesis",
            "yosys",
            subdirs=["log"],
            files={"log/synthesis.log": "ok\n"},
        )

        def snapshot():
            return sorted(
                os.path.join(root, name) for root, _dirs, files in os.walk(ws) for name in files
            )

        before = snapshot()
        cli_main.run(["status", "--workspace", ws])
        cli_main.run(["log", "synthesis", "--workspace", ws, "--json"])
        cli_main.run(["config", "--workspace", ws, "--json"])

        assert snapshot() == before
