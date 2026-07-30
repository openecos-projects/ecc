import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestRunIdResolution:
    def test_status_default_run_id(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "default" in out

    def test_status_simple_token_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_004")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "run_004", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run_004" in out

    def test_status_relative_path_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "sweeps/sweep_001/run_004" in out

    def test_status_absolute_path_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = tmp_path / "ecc-run-004"
        create_flow_json(str(run_dir))

        rc = cli_main.run(["status", "--run-id", str(run_dir), "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run:" in out

    def test_status_missing_run_id(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["status", "--run-id", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_log_preserves_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_005")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "Synthesis",
            "yosys",
            subdirs=["log"],
            files={"log/synthesis.log": "Error: something failed\n"},
        )

        rc = cli_main.run(
            ["log", "synthesis", "--errors", "--run-id", "run_005", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id run_005" in out


class TestRunIdDisclosure:
    def test_explicit_default_preserved_in_disclosure(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id default" in out

    def test_project_relative_run_id_resolves(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "sweeps/sweep_001/run_004" in out


class TestCorruptFlowJson:
    def test_corrupt_flow_json_status_reports_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "corrupt" in out

    def test_missing_flow_json_status_reports_missing(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_corrupt_flow_json_json_reports_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "corrupt"


class TestMissingRunJsonlKind:
    def test_missing_run_jsonl_has_kind(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["status", "--jsonl", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        data = [json.loads(line) for line in out.strip().split("\n") if line.strip()]
        assert data[0]["run"] == "default"
        assert data[0]["status"] == "missing"


class TestConfigRunResolution:
    def test_status_follows_configured_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "exp1",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
            "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
        }

    def test_run_id_overrides_configured_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "other")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "other", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "other",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir} --run-id other",
            "log_cmd": f"ecc log --project {project_dir} --run-id other",
        }

    def test_log_follows_configured_run(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        set_flow_run,
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "Synthesis",
            "yosys",
            subdirs=["log"],
            files={"log/synthesis.log": "Error: something failed\n"},
        )

        rc = cli_main.run(["log", "synthesis", "--errors", "--project", project_dir])

        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id exp1" in out

    def test_config_run_dir_follows_configured_run(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, set_flow_run
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == os.path.join("runs", "exp1")
        assert run_item["resolved"] == os.path.join(project_dir, "runs", "exp1")

    def test_empty_run_id_collapses_to_default_not_config(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        create_flow_json(os.path.join(project_dir, "runs", "exp1"))

        rc = cli_main.run(["status", "--run-id", "", "--project", project_dir, "--json"])

        assert rc == 1
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "default",
            "status": "missing",
            "workspace": os.path.join(project_dir, "runs", "default"),
            "start_cmd": f"ecc run --project {project_dir} --run-id ''",
        }

    def test_empty_run_id_status_success_preserves_selector(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "default",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir} --run-id ''",
            "log_cmd": f"ecc log --project {project_dir} --run-id ''",
        }

    def test_empty_run_id_log_no_logs_preserves_selector(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["log", "--run-id", "", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "log_status": "no_logs",
            "workspace": run_dir,
            "run": f"ecc run --project {project_dir} --run-id ''",
        }

    def test_unreadable_config_falls_back_to_default_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, monkeypatch
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "default",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir}",
            "log_cmd": f"ecc log --project {project_dir}",
        }

    def test_non_utf8_config_falls_back_to_default_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        with open(os.path.join(project_dir, "ecc.toml"), "wb") as f:
            f.write(b'[flow]\nrun = "\xff\xfe"\n')

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "default",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir}",
            "log_cmd": f"ecc log --project {project_dir}",
        }


class TestNamedRunDisclosures:
    def test_status_missing_disclosure_carries_run_id(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["status", "--run-id", "exp1", "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "missing",
                "workspace": os.path.join(project_dir, "runs", "exp1"),
                "start_cmd": f"ecc run --project {project_dir} --run-id exp1",
            }
        ]

    def test_log_no_logs_disclosure_carries_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)

        rc = cli_main.run(["log", "--run-id", "exp1", "--project", project_dir, "--json"])

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "log_status": "no_logs",
                "workspace": run_dir,
                "run": f"ecc run --project {project_dir} --run-id exp1",
            }
        ]


class TestInvalidConfigRun:
    @pytest.mark.parametrize("command", (["status"], ["log"], ["config", "--resolved"]))
    def test_inspection_errors_on_invalid_flow_run(
        self, tmp_path, capsys, create_cli_project, set_flow_run, command
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ""')

        rc = cli_main.run([*command, "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "config_error",
                "reason": "unsupported flow.run: ",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]

    def test_non_string_flow_run_errors(self, tmp_path, capsys, create_cli_project, set_flow_run):
        project_dir = create_cli_project()
        set_flow_run(project_dir, "run = 42")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "config_error",
                "reason": "unsupported flow.run: 42",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]

    def test_config_errors_on_invalid_flow_run_with_run_id(
        self, tmp_path, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ""')

        rc = cli_main.run(
            ["config", "--resolved", "--run-id", "exp1", "--project", project_dir, "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "config_error",
                "reason": "unsupported flow.run: ",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]

    def test_run_id_bypasses_invalid_flow_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ""')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0]["workspace"] == run_dir

    def test_empty_run_id_bypasses_invalid_flow_run_for_status(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ""')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "run": "default",
            "status": "success",
            "workspace": run_dir,
            "inspect_cmd": f"ecc status --project {project_dir} --run-id ''",
            "log_cmd": f"ecc log --project {project_dir} --run-id ''",
        }

    def test_empty_run_id_bypasses_invalid_flow_run_for_log(
        self, tmp_path, capsys, create_cli_project, create_flow_json, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = ""')
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["log", "--run-id", "", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "log_status": "no_logs",
            "workspace": run_dir,
            "run": f"ecc run --project {project_dir} --run-id ''",
        }
