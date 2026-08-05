import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine import StepRunResult


def _set_flow_preset(project_dir, preset):
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        content = f.read()
    content = content.replace('preset = "rtl2gds"', f'preset = "{preset}"')
    with open(toml_path, "w") as f:
        f.write(content)


def _patch_all_flow_builders(monkeypatch):
    markers = {}
    for attr in ("build_rtl2gds_flow", "build_rcx_flow", "build_harden_flow", "build_syn_sta_flow"):
        steps = [("Synthesis", "yosys", "Unstart"), (attr, "ecc", "Unstart")]
        markers[attr] = steps
        monkeypatch.setattr(f"chipcompiler.rtl2gds.builder.{attr}", lambda steps=steps: steps)
    return markers


class TestRun:
    def test_run_calls_create_workspace(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == os.path.join(
            project_dir, "runs", "default"
        )

    def test_run_adds_flow_steps_when_no_init(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert len(flow_mocks.flow.instances[0].added_steps) > 0

    def test_run_calls_create_and_run(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.flow.instances[0].create_called
        assert flow_mocks.flow.instances[0].run_called

    def test_run_overwrite_removes_existing(
        self, tmp_path, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

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
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        def fake_create(**kwargs):
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_when_run_steps_false(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        flow_mocks.flow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_json_uses_non_progress_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "success"
        assert flow_mocks.flow.instances[0].run_called

    def test_run_jsonl_uses_non_progress_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        objects = [json.loads(ln) for ln in out.strip().split("\n")]
        assert any("status" in obj for obj in objects)
        assert flow_mocks.flow.instances[0].run_called

    def test_run_json_no_progress_on_stderr(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "step=" not in err

    def test_run_preserves_final_records(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        record = data["records"][0]
        assert record["run"] == "default"
        assert record["status"] == "success"
        assert "inspect_cmd" in record
        assert "metrics_cmd" not in record
        assert "log_cmd" in record


class TestRunFlowPreset:
    @pytest.mark.parametrize(
        "preset,builder_attr",
        [
            ("rtl2gds", "build_rtl2gds_flow"),
            ("rcx", "build_rcx_flow"),
            ("harden", "build_harden_flow"),
            ("syn_sta", "build_syn_sta_flow"),
        ],
    )
    def test_run_dispatches_builder_for_preset(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks, preset, builder_attr
    ):
        project_dir = create_cli_project()
        _set_flow_preset(project_dir, preset)
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers[builder_attr]

    def test_run_overwrite_rebuilds_flow_with_new_preset(
        self, tmp_path, monkeypatch, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        _set_flow_preset(project_dir, "harden")
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers["build_harden_flow"]

    def test_run_forwards_pdk_overrides(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ndont_use = ["ICG*"]\n')

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {"dont_use": ["ICG*"]}

    def test_run_forwards_resolved_pdk_override_paths(
        self, tmp_path, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write(
                "\n[pdk.overrides]\n"
                'sdc = "constraints/design.sdc"\n'
                f'spef = "{tmp_path}/absolute.spef"\n'
                'dont_use = ["ICG*"]\n'
            )

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "sdc": os.path.join(project_dir, "constraints", "design.sdc"),
            "spef": str(tmp_path / "absolute.spef"),
            "dont_use": ["ICG*"],
        }


class TestWorkspaceRun:
    @pytest.fixture
    def workspace_mocks(self, monkeypatch):
        seen = SimpleNamespace(
            load_path=None,
            has_init=True,
            selected_error=None,
            selected=None,
            create_calls=0,
            executable=None,
            only=None,
            from_step=None,
            resume=False,
            result=StepRunResult(ok=True, executed=("place",)),
        )

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def has_init(self):
                return seen.has_init

            def create_step_workspaces(self, *, executable_steps=None):
                seen.create_calls += 1
                seen.executable = executable_steps

        def selected_step_names(flow, *, from_step=None, only=None, force=False):
            if seen.selected_error is not None:
                raise seen.selected_error
            seen.selected = {"from_step": from_step, "only": only, "force": force}
            if only is not None:
                return [] if not force else [only]
            if from_step is not None:
                return [from_step, "CTS"]
            return ["place", "CTS"]

        def run_only(flow, name, *, force=False):
            seen.only = (name, force)
            return seen.result

        def run_from(flow, name):
            seen.from_step = name
            return seen.result

        def run_resume(flow):
            seen.resume = True
            return seen.result

        def fake_load_workspace(path):
            seen.load_path = path
            return SimpleNamespace(name="workspace")

        monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
        monkeypatch.setattr("chipcompiler.engine.rerun.selected_step_names", selected_step_names)
        monkeypatch.setattr("chipcompiler.engine.rerun.run_only", run_only)
        monkeypatch.setattr("chipcompiler.engine.rerun.run_from", run_from)
        monkeypatch.setattr("chipcompiler.engine.rerun.run_resume", run_resume)
        monkeypatch.setattr(
            "chipcompiler.data.create_workspace",
            lambda **_kwargs: pytest.fail("workspace mode must not create a workspace"),
        )
        return seen

    def test_only_force_wiring(self, workspace_mocks, tmp_path, capsys):
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--force", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.load_path == workspace
        assert workspace_mocks.selected == {"from_step": None, "only": "place", "force": True}
        assert workspace_mocks.executable == {"place"}
        assert workspace_mocks.only == ("place", True)
        assert record["run"] == "workspace"
        assert record["status"] == "success"
        assert record["workspace"] == workspace
        assert record["executed_steps"] == ["place"]
        assert record["no_op"] is False

    def test_default_selector_is_resume(self, workspace_mocks, tmp_path):
        rc = cli_main.run(["run", "--workspace", str(tmp_path / "workspace"), "--plain"])

        assert rc == 0
        assert workspace_mocks.selected == {"from_step": None, "only": None, "force": False}
        assert workspace_mocks.executable == {"place", "CTS"}
        assert workspace_mocks.resume is True

    def test_from_step_wiring(self, workspace_mocks, tmp_path):
        rc = cli_main.run(["run", "--workspace", str(tmp_path / "workspace"), "--from", "CTS"])

        assert rc == 0
        assert workspace_mocks.from_step == "CTS"
        assert workspace_mocks.executable == {"CTS"}

    def test_noop_selection_skips_workspace_rebuild(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.result = StepRunResult(ok=True, executed=())
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.create_calls == 0
        assert workspace_mocks.only == ("place", False)
        assert record == {
            "run": "workspace",
            "status": "success",
            "workspace": workspace,
            "executed_steps": [],
            "no_op": True,
        }

    def test_failed_run_reports_failed_step_and_resume(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.result = StepRunResult(ok=False, executed=(), failed="place")
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record == {
            "run": "workspace",
            "status": "failed",
            "workspace": workspace,
            "executed_steps": [],
            "no_op": False,
            "failed_step": "place",
            "resume_cmd": f"ecc run --workspace {workspace} --resume",
        }

    def test_invalid_workspace(self, tmp_path, capsys):
        rc = cli_main.run(["run", "--workspace", str(tmp_path / "missing"), "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "invalid_workspace"

    def test_missing_flow(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.has_init = False

        rc = cli_main.run(["run", "--workspace", str(tmp_path / "workspace"), "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "missing_flow"

    def test_unknown_step(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.selected_error = ValueError("unknown step 'bogus'")

        rc = cli_main.run(
            ["run", "--workspace", str(tmp_path / "workspace"), "--only", "bogus", "--json"]
        )

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "unknown_step"
        assert "bogus" in record["reason"]

    @pytest.mark.parametrize(
        "argv,error",
        [
            (["--project", "p", "--workspace", "w"], "project_workspace_conflict"),
            (["--run-id", "r", "--workspace", "w"], "project_workspace_conflict"),
            (["--workspace", "w", "--overwrite"], "overwrite_requires_project"),
            (["--workspace", "w", "--set", "place.target_density=0.6"], "set_requires_project"),
            (["--workspace", "w", "--resume", "--only", "place"], "selector_conflict"),
            (["--workspace", "w", "--from", "place", "--only", "CTS"], "selector_conflict"),
            (["--workspace", "w", "--force"], "force_requires_only"),
            (["--resume"], "selector_requires_workspace"),
            (["--from", "place"], "selector_requires_workspace"),
            (["--only", "place"], "selector_requires_workspace"),
            (["--force"], "selector_requires_workspace"),
        ],
    )
    def test_option_conflicts(self, argv, error, capsys, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("conflicts must be rejected before workspace load"),
        )

        rc = cli_main.run(["run", *argv, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == error
