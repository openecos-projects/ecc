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
    for attr in ("build_rtl2gds_flow", "build_syn_sta_flow", "build_synthesis_lec_flow"):
        steps = [("Synthesis", "yosys", "Unstart"), (attr, "ecc", "Unstart")]
        markers[attr] = steps
        monkeypatch.setattr(f"chipcompiler.rtl2gds.builder.{attr}", lambda steps=steps: steps)
    return markers


class TestRun:
    def test_run_calls_create_workspace(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == os.path.join(
            project_dir, "runs", "default"
        )

    def test_run_adds_flow_steps_when_no_init(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert len(flow_mocks.flow.instances[0].added_steps) > 0

    def test_run_calls_create_and_run(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.flow.instances[0].create_called
        assert flow_mocks.flow.instances[0].run_called

    def test_run_overwrite_removes_existing(
        self, tmp_path, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])
        assert rc == 0

    def test_run_fails_if_flow_json_exists(self, tmp_path, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
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
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        def fake_create(**kwargs):
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_when_run_steps_false(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        flow_mocks.flow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_json_uses_non_progress_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

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
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        objects = [json.loads(ln) for ln in out.strip().split("\n")]
        assert any("status" in obj for obj in objects)
        assert flow_mocks.flow.instances[0].run_called

    def test_run_json_no_progress_on_stderr(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "step=" not in err

    def test_run_preserves_final_records(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

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
            ("syn_sta", "build_syn_sta_flow"),
            ("synthesis_lec", "build_synthesis_lec_flow"),
        ],
    )
    def test_run_dispatches_builder_for_preset(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks, preset, builder_attr
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        _set_flow_preset(project_dir, preset)
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers[builder_attr]

    def test_run_overwrite_rebuilds_flow_with_new_preset(
        self, tmp_path, monkeypatch, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        _set_flow_preset(project_dir, "syn_sta")
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers["build_syn_sta_flow"]

    def test_run_preset_flag_overrides_toml(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--preset", "syn_sta"])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers["build_syn_sta_flow"]

    def test_run_preset_flag_does_not_edit_toml(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            before = f.read()
        _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--preset", "syn_sta"])

        assert rc == 0
        with open(toml_path) as f:
            assert f.read() == before

    def test_run_preset_flag_rejects_unknown_preset(
        self, tmp_path, capsys, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--preset", "bogus", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "unsupported_preset"
        assert record["preset"] == "bogus"
        assert "rtl2gds" in record["presets"]
        assert flow_mocks.capture["create_kwargs"] is None

    def test_run_forwards_pdk_overrides(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
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
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write(
                "\n[pdk.overrides]\n"
                'sdc = "constraints/design.sdc"\n'
                'lefs = ["IP/STD_cell/x.lef"]\n'
                f'spef = "{tmp_path}/absolute.spef"\n'
                'dont_use = ["ICG*"]\n'
            )

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "sdc": os.path.join(project_dir, "constraints", "design.sdc"),
            "lefs": [os.path.join(str(tmp_path / "ics55"), "IP", "STD_cell", "x.lef")],
            "spef": str(tmp_path / "absolute.spef"),
            "dont_use": ["ICG*"],
        }

    def test_run_forwards_absolute_paths_with_relative_env_pdk_root(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project(pdk_root="")
        (tmp_path / "ics55").mkdir(exist_ok=True)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\nlefs = ["IP/STD_cell/x.lef"]\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", "ics55")

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "lefs": [os.path.join(str(tmp_path / "ics55"), "IP", "STD_cell", "x.lef")],
        }


class TestWorkspaceRun:
    @pytest.fixture
    def workspace_mocks(self, monkeypatch, tmp_path):
        # The workspace must exist on disk: the locked execution path
        # refuses to even take the sibling lock for an absent target.
        (tmp_path / "workspace").mkdir()
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
            (["--workspace", "w", "--preset", "rtl2gds"], "preset_requires_project"),
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


class TestWorkspaceNoOp:
    def test_complete_workspace_resume_is_noop(self, tmp_path, capsys, monkeypatch):
        import json as _json

        from chipcompiler.data.workspace_config import save_workspace_config

        workspace = tmp_path / "workspace"
        home = workspace / "home"
        home.mkdir(parents=True)
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        chain = [
            (step.value if hasattr(step, "value") else str(step), str(tool))
            for step, tool, _state in build_rtl2gds_flow()
        ]
        steps = [{"name": name, "tool": tool, "state": "Success"} for name, tool in chain]
        (home / "flow.json").write_text(_json.dumps({"steps": steps}))
        assert save_workspace_config(
            workspace,
            {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
            {"preset": "rtl2gds"},
        )
        monkeypatch.setattr(
            "chipcompiler.engine.rerun.run_resume",
            lambda flow: (_ for _ in ()).throw(
                AssertionError("a complete flow must not execute on a no_op reconcile")
            ),
        )

        rc = cli_main.run(["run", "--workspace", str(workspace), "--resume", "--json"])

        assert rc == 0
        record = json.loads(capsys.readouterr().out)["records"][0]
        assert record["status"] == "success"
        assert record["no_op"] is True
        # The adopted narrower target replaced the stale wider one.
        from chipcompiler.data.workspace_config import load_workspace_config

        assert load_workspace_config(workspace)["_flow"] == {"preset": "rtl2gds"}
