import json
import os

from chipcompiler.cli import main as cli_main


class TestCorruptMetricsJson:
    def test_malformed_metrics_reports_corrupt_text(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["analysis"],
            files={"analysis/CTS_metrics.json": "NOT JSON{{{"},
        )
        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "corrupt" in out

    def test_malformed_metrics_reports_corrupt_json(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["analysis"],
            files={"analysis/CTS_metrics.json": "NOT JSON{{{"},
        )
        rc = cli_main.run(["metrics", "cts", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "corrupt"
