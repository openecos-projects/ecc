import json
import os
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main


class DummyFlow:
    has_init_value = False
    run_steps_value = True
    instances = []

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.create_called = False
        self.run_called = False
        self.workspace_steps = []
        DummyFlow.instances.append(self)

    def has_init(self):
        return self.has_init_value

    def add_step(self, step, tool, state):
        self.added_steps.append((step, tool, state))

    def create_step_workspaces(self):
        self.create_called = True

    def run_steps(self):
        self.run_called = True
        return self.run_steps_value

    def run_step(self, workspace_step):
        from chipcompiler.data import StateEnum

        self.run_called = True
        return StateEnum.Success if self.run_steps_value else StateEnum.Imcomplete


def _install_flow_mocks(monkeypatch):
    capture = {"create_kwargs": None}
    workspace_obj = SimpleNamespace(name="workspace")

    DummyFlow.instances = []
    DummyFlow.has_init_value = False
    DummyFlow.run_steps_value = True

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return workspace_obj

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root: None,
    )

    return capture


class TestRun:
    def test_run_calls_create_workspace(self, tmp_path, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert capture["create_kwargs"]["directory"] == os.path.join(project_dir, "runs", "default")

    def test_run_adds_flow_steps_when_no_init(self, tmp_path, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert len(DummyFlow.instances[0].added_steps) > 0

    def test_run_calls_create_and_run(self, tmp_path, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert DummyFlow.instances[0].create_called
        assert DummyFlow.instances[0].run_called

    def test_run_overwrite_removes_existing(
        self, tmp_path, monkeypatch, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])
        assert rc == 0

    def test_run_fails_if_flow_json_exists(self, tmp_path, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_on_config_error(self, tmp_path):
        project_dir = tmp_path / "bad"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design]\n")
        rc = cli_main.run(["run", "--project", str(project_dir)])
        assert rc == 1

    def test_run_fails_when_create_workspace_returns_none(
        self, tmp_path, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        def fake_create(**kwargs):
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_when_run_steps_false(self, tmp_path, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)
        DummyFlow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_json_uses_non_progress_path(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "success"
        assert DummyFlow.instances[0].run_called

    def test_run_jsonl_uses_non_progress_path(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        objects = [json.loads(ln) for ln in out.strip().split("\n")]
        assert any("status" in obj for obj in objects)
        assert DummyFlow.instances[0].run_called

    def test_run_json_no_progress_on_stderr(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "step=" not in err

    def test_run_preserves_final_records(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        record = data["records"][0]
        assert record["run"] == "default"
        assert record["status"] == "success"
        assert "inspect_cmd" in record
        assert "metrics_cmd" in record
        assert "log_cmd" in record
