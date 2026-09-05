"""--workspace resolution shared by the read-only status/log/config commands."""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main


def _make_workspace(project_dir, name="ws"):
    ws = os.path.join(str(project_dir), name)
    os.makedirs(ws)
    return ws


class TestWorkspaceSelection:
    """--workspace names a managed workspace inside --project; the two
    options combine (no conflict) and read-only commands never load the
    workspace."""

    def test_status_resolves_workspace_inside_project(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("read-only commands must not load a workspace"),
        )

        rc = cli_main.run(["status", "--project", str(tmp_path), "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["workspace_id"] == "w"
        assert record["status"] == "missing"
        assert record["workspace"] == str(tmp_path / "w")

    def test_log_rejects_legacy_run_id_option(self, tmp_path, capsys):
        rc = cli_main.run(["log", "--run-id", "r", "--workspace", "w", "--json"])

        captured = capsys.readouterr()
        assert rc == 2
        assert "No such option: --run-id" in captured.err
        assert captured.out == ""

    def test_config_resolves_workspace_inside_project(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("read-only commands must not load a workspace"),
        )

        rc = cli_main.run(["config", "--project", str(tmp_path), "--workspace", "w", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "missing_config"


class TestInvalidWorkspace:
    @pytest.mark.parametrize("command", (["status"], ["log"], ["config"]))
    def test_workspace_path_is_not_a_name(self, tmp_path, capsys, command):
        absent = str(tmp_path / "absent")

        rc = cli_main.run([*command, "--workspace", absent, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "invalid_workspace"
        assert record["reason"] == f"invalid_workspace: {absent!r} is not a single workspace name"


class TestWorkspaceViews:
    def test_status_reads_flow_json(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_step_dir

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_step_dir(ws, "CTS", "ecc")

        rc = cli_main.run(["status", "--project", str(tmp_path), "--workspace", "ws", "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"][0]["workspace"] == ws
        assert data["records"][0]["workspace_id"] == "ws"
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

        rc = cli_main.run(
            ["log", "synthesis", "--project", str(tmp_path), "--workspace", "ws", "--json"]
        )

        records = json.loads(capsys.readouterr().out)["records"]
        assert rc == 0
        assert any("bad thing" in r.get("line", "") for r in records)

    def test_config_step_view(self, tmp_path, capsys, create_flow_json):
        from test.cli.conftest import create_cts_workspace_config

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_cts_workspace_config(ws)

        rc = cli_main.run(
            ["config", "cts", "--project", str(tmp_path), "--workspace", "ws", "--json"]
        )

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
        cli_main.run(["status", "--project", str(tmp_path), "--workspace", "ws"])
        cli_main.run(
            ["log", "synthesis", "--project", str(tmp_path), "--workspace", "ws", "--json"]
        )
        cli_main.run(["config", "--project", str(tmp_path), "--workspace", "ws", "--json"])

        assert snapshot() == before
