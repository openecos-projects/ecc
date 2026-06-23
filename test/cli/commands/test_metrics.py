import json
import os

from chipcompiler.cli import main as cli_main


class TestMetrics:
    def test_metrics_reads_step_metrics(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312, "Cell area": 1840.2}, f)

        rc = cli_main.run(["metrics", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cell_number: 312" in out

    def test_metrics_all_steps(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        for step_dir_name in ["Synthesis_yosys", "Floorplan_ecc"]:
            analysis = os.path.join(run_dir, step_dir_name, "analysis")
            os.makedirs(analysis, exist_ok=True)
            metrics_name = step_dir_name.split("_")[0] + "_metrics.json"
            with open(os.path.join(analysis, metrics_name), "w") as f:
                json.dump({"Cell number": 100}, f)

        rc = cli_main.run(["metrics", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis" in out
        assert "floorplan" in out

    def test_metrics_json(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)

        rc = cli_main.run(["metrics", "synthesis", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert len(data["records"]) == 1
        assert data["records"][0]["metric"] == "cell_number"

    def test_metrics_jsonl(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312, "Cell area": 1840.2}, f)

        rc = cli_main.run(["metrics", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2

    def test_metrics_normalizes_known_keys(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "CTS_ecc", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "CTS_metrics.json"), "w") as f:
            json.dump({"Frequency [MHz]": 450.0, "Die area [μm^2]": "10000.000"}, f)

        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "frequency_mhz: 450.0" in out
        assert "die_area_um2" in out

    def test_metrics_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--project", project_dir])
        assert rc == 1

    def test_metrics_missing_file(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "CTS_ecc", "analysis"), exist_ok=True)

        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out
        assert "ecc log cts" in out

    def test_metrics_json_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "unknown_step"
        assert data["records"][0]["step"] == "nonexistent"

    def test_metrics_json_missing_file(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "CTS_ecc", "analysis"), exist_ok=True)

        rc = cli_main.run(["metrics", "cts", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "missing"

    def test_metrics_jsonl_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--jsonl", "--project", project_dir])
        assert rc == 1
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert objects[0]["status"] == "unknown_step"


class TestFlowOnlyStepMetrics:
    """Step in flow.json but no step directory should report missing, not unknown."""

    def test_metrics_flow_only_step_is_missing(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": [{"name": "CTS", "state": "unstart"}]}, f)

        rc = cli_main.run(["metrics", "cts", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("status") == "missing"
        assert data["records"][0].get("status") != "unknown_step"
