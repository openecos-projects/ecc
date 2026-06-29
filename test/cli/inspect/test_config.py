import json
import os

from chipcompiler.cli import main as cli_main


class TestConfigResolved:
    def test_config_resolved_project(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "design.name" in out
        assert "project:" in out
        assert "pdk.name" in out
        assert "run_dir" in out

    def test_config_resolved_json(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        keys = [item["config"] for item in data["records"]]
        assert "design.name" in keys
        assert "pdk.name" in keys
        assert "run_dir" in keys

    def test_config_resolved_default_run_dir_value(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == "runs/default"

    def test_config_resolved_jsonl(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        keys = [o["config"] for o in objects]
        assert "design.name" in keys

    def test_config_resolved_pdk_root_from_env(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        pdk_root = tmp_path / "ics55_env"
        pdk_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(pdk_root))

        project_dir = create_cli_project(pdk_root="")

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        pdk_item = next(i for i in data["records"] if i["config"] == "pdk.root")
        assert pdk_item["source"] == "env"

    def test_config_resolved_run_id(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(
            [
                "config",
                "--resolved",
                "--run-id",
                "sweeps/sweep_001/run_004",
                "--json",
                "--project",
                project_dir,
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == "sweeps/sweep_001/run_004"

    def test_config_missing_config(self, tmp_path, capsys):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_config_missing_config_json_has_kind_error(self, tmp_path, capsys):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir), "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["kind"] == "error"
        assert record["error"] == "missing_config"

    def test_config_missing_config_jsonl_has_kind_error(self, tmp_path, capsys):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir), "--jsonl"])
        assert rc == 1
        record = json.loads(capsys.readouterr().out.strip())
        assert record["kind"] == "error"
        assert record["error"] == "missing_config"

    def test_config_missing_config_text_has_kind_error(self, tmp_path, capsys):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "[error]" in out
        assert "missing_config" in out
        assert "ecc check" in out
        assert str(project_dir) in out

    def test_config_requires_resolved(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--project", project_dir])
        assert rc != 0
        assert "--resolved" in capsys.readouterr().err


class TestConfigStepResolved:
    def test_config_step_lists_files(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_workspace_config,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_workspace_config(
            run_dir,
            {
                "flow_config.json": "{}",
                "db_default_config.json": "{}",
                "cts_default_config.json": "{}",
            },
        )

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step:" in out or "cts" in out
        assert "step:" in out or "step:" in out
        assert "runs/default/config/flow_config.json" in out
        assert "runs/default/config/db_default_config.json" in out
        assert "cts_default_config.json" in out

    def test_config_step_json(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_workspace_config,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_workspace_config(
            run_dir,
            {
                "flow_config.json": "{}",
                "db_default_config.json": "{}",
                "cts_default_config.json": "{}",
            },
        )

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        records = data["records"]
        assert all(item["scope"] == "step" for item in records)
        assert all(item["step"] == "cts" for item in records)
        assert all(item["source"] == "workspace_config" for item in records)
        assert [item["path"] for item in records] == [
            "runs/default/config/flow_config.json",
            "runs/default/config/db_default_config.json",
            "runs/default/config/cts_default_config.json",
        ]

    def test_config_step_workspace_records_inspect_with_config_command(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert all(
            item["inspect"] == f"ecc config cts --resolved --json --project {project_dir}"
            for item in data["records"]
        )

    def test_config_step_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["config", "nonexistent", "--resolved", "--project", project_dir])
        assert rc == 1

    def test_config_step_no_config_files(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0

    def test_config_dreamplace_legalization_uses_dreamplace_config(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_dreamplace_workspace_config,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
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
        create_step_dir(run_dir, "legalization", "dreamplace", subdirs=["output"])
        create_dreamplace_workspace_config(run_dir)

        rc = cli_main.run(
            ["config", "legalization", "--resolved", "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert [item["path"] for item in data["records"]] == [
            "runs/default/config/dreamplace.json",
        ]
        assert data["records"][0]["source"] == "workspace_config"

    def test_config_workspace_backed_ecc_steps(
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
            create_step_dir(run_dir, step_name, "ecc", subdirs=["output"])
            create_ecc_workspace_config(run_dir, step_config)

            rc = cli_main.run(
                ["config", step_token, "--resolved", "--json", "--project", project_dir]
            )
            assert rc == 0
            data = json.loads(capsys.readouterr().out)
            assert [item["path"] for item in data["records"]] == [
                "runs/default/config/flow_config.json",
                "runs/default/config/db_default_config.json",
                f"runs/default/config/{step_config}",
            ]
            assert all(item["source"] == "workspace_config" for item in data["records"])

    def test_config_sta_uses_rcx_and_sta_workspace_configs(
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
        create_step_dir(run_dir, "STA", "ecc", subdirs=["output"])
        create_workspace_config(
            run_dir,
            {
                "flow_config.json": "{}",
                "db_default_config.json": "{}",
                "rcx.json": "{}",
                "sta.json": "{}",
            },
        )

        rc = cli_main.run(["config", "sta", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert [item["path"] for item in data["records"]] == [
            "runs/default/config/flow_config.json",
            "runs/default/config/db_default_config.json",
            "runs/default/config/rcx.json",
            "runs/default/config/sta.json",
        ]
        assert all(item["source"] == "workspace_config" for item in data["records"])

    def test_config_yosys_synthesis_does_not_report_ieda_flow_config(
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
        create_step_dir(run_dir, "Synthesis", "yosys", subdirs=["output"])
        create_workspace_config(run_dir, {"flow_config.json": "{}"})

        rc = cli_main.run(["config", "synthesis", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["records"]) == 1
        assert data["records"][0]["step"] == "synthesis"
        assert data["records"][0]["config_status"] == "none"
        assert "path" not in data["records"][0]


class TestEmptyStepConfigSentinel:
    def test_step_no_config_emits_sentinel_text(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cts" in out
        assert "No configuration" in out
        assert "artifacts:" in out

    def test_step_no_config_emits_sentinel_json(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["step"] == "cts"
        assert data["records"][0]["config_status"] == "none"


class TestDirectoryOnlyStepConfig:
    def test_dir_only_step_config_infers_tool_from_step_dir(
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
                {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
            ],
        )
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_cts_workspace_config(run_dir)

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert [item["path"] for item in data["records"]] == [
            "runs/default/config/flow_config.json",
            "runs/default/config/db_default_config.json",
            "runs/default/config/cts_default_config.json",
        ]

    def test_dir_only_step_diagnose_uses_inferred_tool_for_config(
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
                {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
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

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config_unavailable" not in out
        assert "clean" in out


class TestConfigRoleDisclosure:
    def test_config_artifact_has_disclosure(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        has_disclosure,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["config"], files={"config/cts_config.json": "{}"}
        )

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)


class TestAbsoluteRunIdConfig:
    def test_absolute_run_id_preserves_run_dir_value(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        external_run = tmp_path / "external_run"
        create_flow_json(str(external_run))

        rc = cli_main.run(
            [
                "config",
                "--resolved",
                "--run-id",
                str(external_run),
                "--json",
                "--project",
                project_dir,
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == str(external_run)


class TestConfigTextUsesItemInspectCmd:
    def test_run_dir_text_uses_status_command(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run_dir" in out
        assert "ecc status" in out


class TestConfigJsonDisclosure:
    def test_project_config_json_has_inspect_cmd(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for item in data["records"]:
            assert "inspect" in item, f"Missing inspect in item: {item['config']}"


class TestIsolatedConfigValidation:
    @staticmethod
    def _valid_toml(tmp_path, **overrides):
        pdk_dir = tmp_path / "pdk"
        pdk_dir.mkdir(exist_ok=True)
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir(exist_ok=True)
        (rtl_dir / "gcd.v").write_text("module gcd; endmodule")
        defaults = {
            "name": "gcd",
            "top": "gcd",
            "rtl": '["rtl/gcd.v"]',
            "clock_port": "clk",
            "frequency_mhz": "100.0",
            "pdk_name": "ics55",
            "pdk_root": str(pdk_dir),
            "flow_preset": "rtl2gds",
            "flow_run": "default",
        }
        defaults.update(overrides)
        return f'''[design]
name = "{defaults["name"]}"
top = "{defaults["top"]}"
rtl = {defaults["rtl"]}
clock_port = "{defaults["clock_port"]}"
frequency_mhz = {defaults["frequency_mhz"]}

[pdk]
name = "{defaults["pdk_name"]}"
root = "{defaults["pdk_root"]}"

[flow]
preset = "{defaults["flow_preset"]}"
run = "{defaults["flow_run"]}"
'''

    def test_unsupported_flow_run_rejected(
        self, tmp_path, capsys, monkeypatch, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = tmp_path / "bad_run"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, flow_run="custom")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_empty_clock_port_rejected(self, tmp_path, capsys, monkeypatch, mock_pdk_validation):
        mock_pdk_validation()
        project_dir = tmp_path / "bad_clock"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, clock_port="")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_zero_frequency_rejected(self, tmp_path, capsys, monkeypatch, mock_pdk_validation):
        mock_pdk_validation()
        project_dir = tmp_path / "bad_freq"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, frequency_mhz="0")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_empty_rtl_rejected(self, tmp_path, capsys, monkeypatch, mock_pdk_validation):
        mock_pdk_validation()
        project_dir = tmp_path / "bad_rtl"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, rtl="[]")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1


class TestRtlPathResolution:
    def test_absolute_rtl_resolved_correctly(
        self, tmp_path, capsys, monkeypatch, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        rtl_dir = tmp_path / "external_rtl"
        rtl_dir.mkdir()
        (rtl_dir / "gcd.v").write_text("module gcd; endmodule")
        (project_dir / "ecc.toml").write_text(f'''[design]
name = "gcd"
top = "gcd"
rtl = ["{rtl_dir / "gcd.v"}"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "{tmp_path / "pdk"}"

[flow]
preset = "rtl2gds"
run = "default"
''')
        (tmp_path / "pdk").mkdir(exist_ok=True)
        rc = cli_main.run(["config", "--resolved", "--json", "--project", str(project_dir)])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        rtl_item = next(i for i in data["records"] if i["config"] == "design.rtl.0")
        assert rtl_item["resolved"] == str(rtl_dir / "gcd.v")
