import json
import os

from chipcompiler.cli import main as cli_main


class TestStatus:
    def test_status_reads_flow_json(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[status]" in out
        assert "synthesis" in out
        assert "floorplan" in out

    def test_status_json(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        records = data["records"]
        assert records[0]["run"] == "default"
        assert records[0]["status"] == "success"
        step_records = [r for r in records if "step" in r]
        assert len(step_records) == 2

    def test_status_jsonl(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir, "--jsonl"])
        assert rc == 0
        lines = capsys.readouterr().out.strip().split("\n")
        objects = [json.loads(ln) for ln in lines]
        assert "run" in objects[0]
        assert "step" in objects[1]

    def test_status_normalizes_step_names(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:18"},
                {"name": "place", "tool": "dreamplace", "state": "Success", "runtime": "0:01:12"},
            ],
        )

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis" in out
        assert "placement" in out

    def test_status_missing_run(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out
        assert "ecc run" in out

    def test_status_invalid_flow_json(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("not valid json{{{")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1


class TestCorruptFlowJson:
    """Non-dict flow.json must be reported as corrupt, not missing."""

    def test_array_flow_json_is_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump([], f)

        rc = cli_main.run(["status", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("status") == "corrupt"

    def test_string_flow_json_is_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump("bad", f)

        rc = cli_main.run(["status", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("status") == "corrupt"
