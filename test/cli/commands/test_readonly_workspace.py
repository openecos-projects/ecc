"""--workspace resolution shared by the read-only status/log/config commands."""

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

    def test_status_resolves_workspace_inside_project(
        self, tmp_path, capsys, monkeypatch, plain_records
    ):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("read-only commands must not load a workspace"),
        )

        rc = cli_main.run(["status", "--project", str(tmp_path), "--workspace", "w", "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["workspace_id"] == "w"
        assert record["status"] == "missing"
        assert record["workspace"] == str(tmp_path / "w")

    def test_log_rejects_legacy_run_id_option(self, tmp_path, capsys):
        rc = cli_main.run(["log", "--run-id", "r", "--workspace", "w", "--plain"])

        captured = capsys.readouterr()
        assert rc == 2
        assert "No such option: --run-id" in captured.err
        assert captured.out == ""

    def test_config_resolves_workspace_inside_project(
        self, tmp_path, capsys, monkeypatch, plain_records
    ):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("read-only commands must not load a workspace"),
        )

        rc = cli_main.run(["config", "--project", str(tmp_path), "--workspace", "w", "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "missing_config"


class TestInvalidWorkspace:
    @pytest.mark.parametrize("command", (["status"], ["log"], ["config"]))
    def test_workspace_path_is_not_a_name(self, tmp_path, capsys, command, plain_records):
        absent = str(tmp_path / "absent")

        rc = cli_main.run([*command, "--workspace", absent, "--plain"])

        record = plain_records(capsys.readouterr().out)[0]
        assert rc == 1
        assert record["error"] == "invalid_workspace"
        assert record["reason"] == f"invalid_workspace: {absent!r} is not a single workspace name"


class TestWorkspaceViews:
    def test_status_reads_flow_json(self, tmp_path, capsys, create_flow_json, plain_records):
        from test.cli.conftest import create_step_dir

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_step_dir(ws, "CTS", "ecc")

        rc = cli_main.run(["status", "--project", str(tmp_path), "--workspace", "ws", "--plain"])

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert records[0]["workspace"] == ws
        assert records[0]["workspace_id"] == "ws"
        assert any(r.get("step") == "cts" for r in records[1:])

    def test_log_reads_step_log(self, tmp_path, capsys, create_flow_json, plain_records):
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
            ["log", "synthesis", "--project", str(tmp_path), "--workspace", "ws", "--plain"]
        )

        records = plain_records(capsys.readouterr().out)
        assert rc == 0
        assert any("bad thing" in r.get("line", "") for r in records)

    def test_config_step_view(self, tmp_path, capsys, create_flow_json, plain_records):
        from test.cli.conftest import create_cts_workspace_config

        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")
        create_cts_workspace_config(ws)

        rc = cli_main.run(
            ["config", "cts", "--project", str(tmp_path), "--workspace", "ws", "--plain"]
        )

        records = plain_records(capsys.readouterr().out)
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
        cli_main.run(["log", "synthesis", "--project", str(tmp_path), "--workspace", "ws"])
        cli_main.run(["config", "--project", str(tmp_path), "--workspace", "ws"])

        assert snapshot() == before


class TestUnknownStepErrors:
    """unknown_step failures carry the standard error-record shape so the
    text renderer prints a readable message instead of empty fields."""

    def test_config_unknown_step_text(self, tmp_path, capsys, create_flow_json):
        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")

        rc = cli_main.run(["config", "nope", "--project", str(tmp_path), "--workspace", "ws"])

        assert rc == 1
        out = capsys.readouterr().out
        assert "[error]" in out
        assert "unknown_step" in out
        assert "nope" in out

    def test_config_unknown_step_plain(self, tmp_path, capsys, create_flow_json, plain_records):
        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")

        rc = cli_main.run(
            ["config", "nope", "--project", str(tmp_path), "--workspace", "ws", "--plain"]
        )

        assert rc == 1
        record = plain_records(capsys.readouterr().out)[0]
        assert record["kind"] == "error"
        assert record["error"] == "unknown_step"
        assert record["step"] == "nope"

    def test_log_unknown_step_plain(self, tmp_path, capsys, create_flow_json, plain_records):
        ws = _make_workspace(tmp_path)
        create_flow_json(ws, profile="inspect")

        rc = cli_main.run(
            ["log", "nope", "--project", str(tmp_path), "--workspace", "ws", "--plain"]
        )

        assert rc == 1
        record = plain_records(capsys.readouterr().out)[0]
        assert record["kind"] == "error"
        assert record["error"] == "unknown_step"
