import json
import os

from chipcompiler.cli import main as cli_main


class TestRunDirectory:
    def test_run_id_bare_name_writes_under_runs(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
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
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "sweeps/s1/r4", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "sweeps", "s1", "r4")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
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
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        abs_run = str(tmp_path / "abs_run")

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", abs_run, "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == abs_run
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
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
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
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "other", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "other")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
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
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, None)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "default")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
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

    def test_empty_run_id_writes_default_and_preserves_selector(
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "default")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "default",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id ''",
                "log_cmd": f"ecc log --project {project_dir} --run-id ''",
            }
        ]

    def test_empty_run_id_run_exists_preserves_selector(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        set_flow_run,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "default",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id ''",
            }
        ]

    def test_overwrite_rebuilds_named_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]

    def test_run_then_status_reads_persisted_named_run(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        set_flow_run,
        minimal_ics55_pdk_factory,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        set_flow_run(project_dir, 'run = "exp1"')
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.engine.flow.EngineFlow.create_step_workspaces", lambda self: None
        )
        monkeypatch.setattr(
            "chipcompiler.engine.flow.EngineFlow.run_steps", lambda self, *, rerun=False: True
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "unstart",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            },
            {
                "step": "synthesis",
                "tool": "yosys",
                "status": "unstart",
                "runtime": None,
                "log_cmd": f"ecc log synthesis --project {project_dir} --run-id exp1",
            },
        ]

    def test_run_parses_config_once(
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks, monkeypatch
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        from chipcompiler.cli.project import config as config_module

        real_load = config_module.load_project_config
        calls = []

        def counting_load(config_path):
            calls.append(config_path)
            return real_load(config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", counting_load)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        assert len(calls) == 1
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]
