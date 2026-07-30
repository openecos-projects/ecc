import json
import os
from types import SimpleNamespace

import pytest

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
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )

    return capture


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
        self, tmp_path, monkeypatch, create_cli_project, preset, builder_attr
    ):
        project_dir = create_cli_project()
        _set_flow_preset(project_dir, preset)
        _install_flow_mocks(monkeypatch)
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert DummyFlow.instances[0].added_steps == markers[builder_attr]

    def test_run_overwrite_rebuilds_flow_with_new_preset(
        self, tmp_path, monkeypatch, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        _set_flow_preset(project_dir, "harden")
        _install_flow_mocks(monkeypatch)
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])

        assert rc == 0
        assert DummyFlow.instances[0].added_steps == markers["build_harden_flow"]

    def test_run_forwards_pdk_overrides(self, tmp_path, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ndont_use = ["ICG*"]\n')
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        create_kwargs = capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {"dont_use": ["ICG*"]}

    def test_run_forwards_resolved_pdk_override_paths(
        self, tmp_path, monkeypatch, create_cli_project
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
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "sdc": os.path.join(project_dir, "constraints", "design.sdc"),
            "spef": str(tmp_path / "absolute.spef"),
            "dont_use": ["ICG*"],
        }


class TestRunDirectory:
    def test_run_id_bare_name_writes_under_runs(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]

    def test_run_id_relative_path_writes_project_relative(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "sweeps/s1/r4", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "sweeps", "s1", "r4")
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "sweeps/s1/r4",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id sweeps/s1/r4",
                "log_cmd": f"ecc log --project {project_dir} --run-id sweeps/s1/r4",
            }
        ]

    def test_run_id_absolute_path_writes_verbatim(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        capture = _install_flow_mocks(monkeypatch)
        abs_run = str(tmp_path / "abs_run")

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", abs_run, "--json"])

        assert rc == 0
        assert capture["create_kwargs"]["directory"] == abs_run
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": abs_run,
                "status": "success",
                "workspace": abs_run,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id {abs_run}",
                "log_cmd": f"ecc log --project {project_dir} --run-id {abs_run}",
            }
        ]

    def test_configured_flow_run_writes_there(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]

    def test_run_id_overrides_configured_flow_run(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "other", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "other")
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "other",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id other",
                "log_cmd": f"ecc log --project {project_dir} --run-id other",
            }
        ]

    def test_absent_flow_run_key_matches_default_records(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, None)
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "default")
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "default",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir}",
                "log_cmd": f"ecc log --project {project_dir}",
            }
        ]

    def test_run_exists_for_named_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "exp1",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id exp1",
            }
        ]

    def test_overwrite_rebuilds_named_run(
        self, tmp_path, monkeypatch, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir, profile="main")
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]


class TestOverwriteGuard:
    def test_refuses_foreign_non_empty_dir(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.chmod(keep, 0o400)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        os.chmod(keep, 0o644)

    def test_refuses_symlink_target(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        link = os.path.join(project_dir, "runs", "exp1")
        os.symlink(real_run, link)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": link,
                "reason": "target is not an ECC run directory",
            }
        ]
        assert os.path.islink(link)
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_non_directory_target(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        target = os.path.join(project_dir, "runs", "exp1")
        with open(target, "w") as f:
            f.write("not a directory\n")

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": target,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(target) as f:
            assert f.read() == "not a directory\n"

    def test_allows_empty_dir(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert capture["create_kwargs"]["directory"] == run_dir

    def test_refuses_home_symlink(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(os.path.join(real_run, "home"), os.path.join(run_dir, "home"))

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_flow_json_symlink(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(os.path.join(run_dir, "home"))
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(
            os.path.join(real_run, "home", "flow.json"),
            os.path.join(run_dir, "home", "flow.json"),
        )

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))


class TestRunDirAliasRefusal:
    @pytest.mark.parametrize(
        ("run_id", "workspace"),
        [
            (".", os.path.join("runs", ".")),
            ("..", os.path.join("runs", "..")),
            ("runs/default/..", os.path.join("runs", "default", "..")),
        ],
    )
    def test_aliasing_run_id_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, run_id, workspace
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        marker = os.path.join(project_dir, "runs", "other_run")
        os.makedirs(marker)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", run_id, "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": run_id,
                "workspace": os.path.join(project_dir, workspace),
                "reason": "run id must not resolve to the project or runs container",
            }
        ]
        assert os.path.isdir(marker)

    def test_absolute_project_dir_run_id_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": project_dir,
                "workspace": project_dir,
                "reason": "run id must not resolve to the project or runs container",
            }
        ]

    def test_configured_dotdot_run_refused(
        self, tmp_path, capsys, create_cli_project, set_flow_run, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ".."')

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": "..",
                "workspace": os.path.join(project_dir, "runs", ".."),
                "reason": "run id must not resolve to the project or runs container",
            }
        ]
