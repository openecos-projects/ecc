import json
import os

from chipcompiler.cli import main as cli_main


class TestDiagnose:
    def test_diagnose_missing_run(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing_run" in out
        assert "error:" in out

    def test_diagnose_invalid_flow_json(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "invalid_flow_json" in out

    def test_diagnose_failed_step(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["log", "analysis"],
            files={"log/cts.log": "Error: failed\n", "analysis/CTS_metrics.json": "{}"},
        )

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "failed_step" in out
        assert "error:" in out

    def test_diagnose_ongoing_step_warning(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Ongoing", "runtime": ""},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "running\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ongoing_step" in out
        assert "warning:" in out

    def test_diagnose_unstarted_step_info(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Unstart", "runtime": ""},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "unstarted_step" in out
        assert "info:" in out

    def test_diagnose_log_errors_count(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "Error: bad thing\nError: other bad\nok line\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "log_errors" in out
        assert "count: 2" in out

    def test_diagnose_missing_metrics_warning(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing_metrics" in out
        assert "warning:" in out

    def test_diagnose_missing_artifacts_warning(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)
        # Remove investigation role dirs to trigger missing_artifacts
        import shutil

        shutil.rmtree(os.path.join(run_dir, "CTS_ecc", "analysis"))

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing_artifacts" in out
        assert "warning:" in out

    def test_diagnose_config_unavailable_info(
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" in out
        assert "info:" in out

    def test_diagnose_clean_run(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": json.dumps({"Frequency [MHz]": 450.0}),
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "clean" in out

    def test_diagnose_uses_workspace_config_without_step_config(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" not in out
        assert "clean" in out

    def test_diagnose_dreamplace_legalization_uses_dreamplace_config(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_dreamplace_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {
                    "name": "legalization",
                    "tool": "dreamplace",
                    "state": "Success",
                    "runtime": "0:00:04",
                },
            ],
        )
        create_step_dir(
            run_dir,
            "legalization",
            "dreamplace",
            subdirs=["log", "output", "analysis"],
            files={
                "log/legalization.log": "ok\n",
                "output/design.def": "def",
                "analysis/legalization_metrics.json": "{}",
            },
        )
        create_dreamplace_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "legalization", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" not in out
        assert "clean" in out

    def test_diagnose_workspace_backed_ecc_steps(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_ecc_workspace_config,
    ):
        cases = [
            ("PNP", "pnp", "pnp_default_config.json"),
            ("optDrv", "optdrv", "to_default_config_drv.json"),
            ("optHold", "opthold", "to_default_config_hold.json"),
            ("optSetup", "optsetup", "to_default_config_setup.json"),
        ]
        for step_name, step_token, step_config in cases:
            project_dir = create_cli_project(name=f"gcd_{step_token}")
            run_dir = os.path.join(project_dir, "runs", "default")
            create_flow_json(
                run_dir,
                [
                    {
                        "name": step_name,
                        "tool": "ecc",
                        "state": "Success",
                        "runtime": "0:00:04",
                    },
                ],
            )
            create_step_dir(
                run_dir,
                step_name,
                "ecc",
                subdirs=["log", "output", "analysis"],
                files={
                    f"log/{step_name}.log": "ok\n",
                    "output/design.def": "def",
                    f"analysis/{step_name}_metrics.json": "{}",
                },
            )
            create_ecc_workspace_config(run_dir, step_config)

            rc = cli_main.run(["diagnose", step_token, "--project", project_dir])
            assert rc == 0
            out = capsys.readouterr().out
            assert "config_unavailable" not in out
            assert "clean" in out

    def test_diagnose_sta_uses_rcx_workspace_config(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {
                    "name": "STA",
                    "tool": "ecc",
                    "state": "Success",
                    "runtime": "0:00:04",
                },
            ],
        )
        create_step_dir(
            run_dir,
            "STA",
            "ecc",
            subdirs=["log", "output", "analysis"],
            files={
                "log/STA.log": "ok\n",
                "output/design.def": "def",
                "analysis/STA_metrics.json": "{}",
            },
        )
        create_workspace_config(
            run_dir,
            {
                "flow_config.json": "{}",
                "db_default_config.json": "{}",
                "rcx.json": "{}",
                "sta.json": "{}",
            },
        )

        rc = cli_main.run(["diagnose", "sta", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" not in out
        assert "clean" in out

    def test_diagnose_yosys_synthesis_reports_config_unavailable(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {
                    "name": "Synthesis",
                    "tool": "yosys",
                    "state": "Success",
                    "runtime": "0:00:05",
                },
            ],
        )
        create_step_dir(
            run_dir,
            "Synthesis",
            "yosys",
            subdirs=["log", "output", "analysis"],
            files={
                "log/Synthesis.log": "ok\n",
                "output/design.v": "verilog",
                "analysis/Synthesis_metrics.json": "{}",
            },
        )
        create_workspace_config(run_dir, {"flow_config.json": "{}"})

        rc = cli_main.run(["diagnose", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" in out
        assert "info:" in out

    def test_diagnose_step_filter(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir,
            "Synthesis",
            "yosys",
            subdirs=["output", "log", "analysis", "config"],
            files={
                "output/synth.v": "verilog",
                "log/synthesis.log": "ok\n",
                "analysis/Synthesis_metrics.json": "{}",
                "config/config.json": "{}",
            },
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: failed\n"}
        )

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "failed_step" in out
        assert "cts" in out
        assert "synthesis" not in out

    def test_diagnose_unknown_step(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["diagnose", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "unknown_step" in out

    def test_diagnose_no_repair_suggestions(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: failed\n"}
        )

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "suggest" not in out.lower()
        assert "fix" not in out.lower()
        assert "recommend" not in out.lower()

    def test_diagnose_json(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: failed\n"}
        )

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert any(i["issue"] == "failed_step" for i in data["records"])

    def test_diagnose_jsonl(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: failed\n"}
        )

        rc = cli_main.run(["diagnose", "--jsonl", "--project", project_dir])
        assert rc == 1
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert any(o["issue"] == "failed_step" for o in objects)

    def test_diagnose_with_run_id(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_007")
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--run-id", "run_007", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "clean" in out


class TestDiagnoseExitCodes:
    def test_error_issue_returns_nonzero(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: failed\n"}
        )

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1

    def test_warning_only_returns_zero(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Ongoing", "runtime": ""},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "running\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0

    def test_clean_run_returns_zero(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0

    def test_failed_step_not_zero(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(run_dir, "CTS", "ecc")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc != 0


class TestDiagnoseFlowOnlySteps:
    def test_flow_step_without_directory_emits_issues(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "failed_step" in out
        assert "cts" in out
        assert "unknown_step" not in out

    def test_flow_step_without_dir_reports_missing_artifacts(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
            ],
        )

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing_artifacts" in out
        assert "missing_metrics" in out
        assert "config_unavailable" in out


class TestDiagnoseIssueSpecificEvidence:
    def test_log_errors_uses_log_command(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "Error: bad thing\nError: other\nok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "log_errors" in out
        assert "ecc log cts" in out

    def test_missing_metrics_uses_metrics_command(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing_metrics" in out
        assert "ecc metrics cts" in out

    def test_missing_artifacts_uses_artifacts_command(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log"],
            files={"log/cts.log": "ok\n"},
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing_artifacts" in out
        assert "ecc artifacts cts" in out

    def test_config_unavailable_uses_config_command(
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" in out
        assert "ecc config cts --resolved" in out

    def test_invalid_flow_json_has_evidence(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "invalid_flow_json" in out
        assert "evidence:" in out
        assert "ecc status" in out

    def test_invalid_flow_json_json_has_evidence(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        issue = data["records"][0]
        assert issue["issue"] == "invalid_flow_json"
        assert "evidence" in issue
        assert "start_cmd" in issue


class TestCleanDiagnoseOutput:
    def test_clean_has_status_and_disclosure_commands(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "clean" in out
        assert "inspect:" in out
        assert "artifacts:" in out
        assert "config:" in out

    def test_clean_json_has_disclosure_metadata(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": "{}",
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "clean"
        assert "inspect_cmd" in data["records"][0]
        assert "artifacts" in data["records"][0]
        assert "config" in data["records"][0]


class TestPendingStepDiagnose:
    def test_pending_step_creates_issue(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Pending", "runtime": ""},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": "ok\n",
                "output/design.def": "def",
                "analysis/CTS_metrics.json": '{"freq": 100}',
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "pending_step" in out
        assert "pending" in out


class TestLogErrorMatching:
    def test_clean_summary_not_counted_as_error(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": (
                    "CTS completed successfully\n0 errors\nNo errors found\n0 failed checks\n"
                ),
                "output/design.def": "def",
                "analysis/CTS_metrics.json": '{"freq": 100}',
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "log_errors" not in out

    def test_real_errors_still_detected(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
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
            subdirs=["log", "output", "analysis"],
            files={
                "log/cts.log": (
                    "CTS completed\nError: bad thing\nTraceback (most recent call):\n0 errors\n"
                ),
                "output/design.def": "def",
                "analysis/CTS_metrics.json": '{"freq": 100}',
            },
        )
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "log_errors" in out
        assert "count: 2" in out
