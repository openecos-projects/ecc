import json
import os

from chipcompiler.cli import main as cli_main


class TestVirginFirstRun:
    def test_virgin_run_generates_manifest_at_root_layout(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "default")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        records = manifest_stubs.records()
        assert records[0]["status"] == "success"
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

        manifest = json.loads((tmp_path / "gcd" / "project.json").read_text())
        assert manifest["schema_version"] == 1
        assert manifest["design_name"] == "gcd"
        assert manifest["root_path"] == project_dir
        assert manifest["project_id"].startswith("proj_")
        assert manifest["objectives"]["primary"] == "timing"
        assert manifest["mpc"] is None
        assert manifest["best_workspace"] is None
        assert manifest["qor_baseline"]["workspace_id"] == "default"
        (entry,) = manifest["workspaces"]
        assert entry["workspace_id"] == "default"
        assert entry["workspace_path"] == run_dir
        assert entry["start_step"] == "Synth"
        assert entry["end_step"] == "Filler"
        # The DummyFlow run succeeds, so the D4 write-back finalizes the
        # initial "running" status.
        assert entry["status"] == "success"
        assert entry["parameter_patch"] == {}
        # The complete D3 source shape, GUI-flat parameters included.
        assert manifest["base_design"] == {
            "pdk": "ics55",
            "pdk_root": str(tmp_path / "ics55"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "origin_verilog": "rtl/gcd.v",
            "parameters": {
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "frequency_max": 100.0,
                "die_area_mode": "utilitization_margin",
            },
        }

    def test_virgin_run_set_values_stay_out_of_manifest(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(
            ["run", "--project", project_dir, "--set", "synth.max_fanout=16", "--json"]
        )

        assert rc == 0
        manifest = json.loads((tmp_path / "gcd" / "project.json").read_text())
        assert "max_fanout" not in manifest["base_design"]["parameters"]
        assert manifest["base_design"]["parameters"]["frequency_max"] == 100.0

    def test_virgin_run_failed_writes_back_failed(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        flow_mocks.flow.run_steps_value = False
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        manifest = json.loads((tmp_path / "gcd" / "project.json").read_text())
        assert manifest["workspaces"][0]["status"] == "failed"

    def test_virgin_run_rejects_nested_run_id(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "sweeps/s1", "--json"])

        assert rc != 0
        (record,) = manifest_stubs.records()
        assert record["error"] == "invalid_run_id"

    def test_virgin_run_warns_when_the_winner_is_unusable(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs
    ):
        project_dir = create_cli_project()
        # A directory sitting at the project.json path: the create link
        # loses, the "winner" cannot load, and the run must say so instead
        # of silently succeeding without a usable manifest.
        os.mkdir(os.path.join(project_dir, "project.json"))

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        (warning,) = [r for r in records if r.get("warning") == "manifest_generation_failed"]
        assert "GUI" in warning["reason"]
        assert flow_mocks.capture["create_kwargs"] is not None
        assert not os.path.isfile(os.path.join(project_dir, "project.json"))

    def test_virgin_run_warns_when_no_manifest_winner_exists(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs, monkeypatch
    ):
        project_dir = create_cli_project()
        # The write itself failed (nothing ever landed at project.json):
        # same loud outcome — never a quiet success.
        monkeypatch.setattr(
            "chipcompiler.cli.project.manifest.write_manifest_if_absent",
            lambda *args, **kwargs: False,
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert any(r.get("warning") == "manifest_generation_failed" for r in records)
        assert flow_mocks.capture["create_kwargs"] is not None
        assert not os.path.exists(os.path.join(project_dir, "project.json"))


class TestManifestRunCommand:
    def test_undeclared_run_id_creates_at_root_with_warning(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(["run", "--project", str(project_dir), "--run-id", "exp2", "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == str(project_dir / "exp2")
        records = manifest_stubs.records()
        warning = [r for r in records if r.get("warning") == "workspace_not_registered"]
        assert len(warning) == 1
        # No manifest entry is added for undeclared runs.
        manifest = json.loads((project_dir / "project.json").read_text())
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["ws_0001"]

    def test_declared_workspace_run_writes_back_status(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == str(project_dir / "ws_0001")
        manifest = json.loads((project_dir / "project.json").read_text())
        assert manifest["workspaces"][0]["status"] == "success"

    def test_write_back_failure_degrades_to_warning(
        self, tmp_path, capsys, flow_mocks, manifest_stubs, monkeypatch
    ):
        """AC-10: a failed status write-back never changes the run result —
        the successful run stays successful with exactly one
        manifest_write_back_failed warning."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir, [manifest_stubs.entry(project_dir, "ws_0001", status="running")]
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.manifest.write_back_workspace_status",
            lambda project_dir, workspace_id, status: False,
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        statuses = [r for r in records if r.get("status") == "success"]
        assert len(statuses) == 1
        warnings = [r for r in records if r.get("warning") == "manifest_write_back_failed"]
        assert len(warnings) == 1
        # The on-disk manifest keeps its pre-run entry status.
        manifest = json.loads((project_dir / "project.json").read_text())
        assert manifest["workspaces"][0]["status"] == "running"


class TestOriginDefResolution:
    """base_design.origin_def reaches workspace creation on both layering
    paths; relative spellings resolve against the project root (never the
    process cwd), absolute spellings pass through."""

    def _project(self, manifest_stubs, tmp_path, origin_def, hybrid):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "origin_def": origin_def,
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
        )
        if hybrid:
            # Partial ecc.toml without [flow]: creation seeds the ledger from
            # the entry range, which the flow mock emulates via has_init.
            (project_dir / "ecc.toml").write_text("[design]\nfrequency_mhz = 100.0\n")
        return project_dir

    def test_manifest_only_relative_def_resolved_against_project(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = self._project(manifest_stubs, tmp_path, "inputs/gcd.def", hybrid=False)

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["origin_def"] == str(
            project_dir / "inputs" / "gcd.def"
        )

    def test_hybrid_relative_def_resolved_against_project(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = self._project(manifest_stubs, tmp_path, "inputs/gcd.def", hybrid=True)
        flow_mocks.flow.has_init_value = True

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["origin_def"] == str(
            project_dir / "inputs" / "gcd.def"
        )

    def test_absolute_def_preserved(self, tmp_path, capsys, flow_mocks, manifest_stubs):
        absolute = str(tmp_path / "elsewhere" / "gcd.def")
        project_dir = self._project(manifest_stubs, tmp_path, absolute, hybrid=True)
        flow_mocks.flow.has_init_value = True

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["origin_def"] == absolute


class TestHybridLayering:
    def test_ecc_toml_overlays_manifest_base(self, tmp_path, capsys, flow_mocks, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"frequency_max": 50, "max_fanout": 12},
            },
        )
        # Partial ecc.toml: only the frequency is overridden.
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 200.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "'
            + str(project_dir / "pdk")
            + '"\n\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["frequency_max"] == 200.0  # ecc.toml wins
        assert parameters["max_fanout"] == 12  # manifest base survives
        assert flow_mocks.capture["create_kwargs"]["directory"] == str(project_dir / "ws_0001")

    def test_manifest_origin_verilog_fallback(self, tmp_path, capsys, flow_mocks):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "pdk").mkdir()
        (project_dir / "src").mkdir()
        (project_dir / "src" / "gcd.v").write_text("module gcd; endmodule\n")
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": str(project_dir),
            "base_design": {
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": [],
                "origin_verilog": "src/gcd.v",
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
            "workspaces": [
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(project_dir / "ws_0001"),
                }
            ],
        }
        (project_dir / "project.json").write_text(json.dumps(document))

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["origin_verilog"].endswith("src/gcd.v")


class TestExistingRunGuards:
    def test_empty_flow_ledger_is_an_error(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, manifest_stubs
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)
        from chipcompiler.data.workspace_config import save_workspace_config

        assert save_workspace_config(
            run_dir,
            {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
            {"preset": "rtl2gds"},
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        record, hint = manifest_stubs.records()
        assert record["error"] == "invalid_flow_json"
        assert hint["warning"] == "legacy_layout_detected"


class TestHybridFullLayering:
    def test_partial_ecc_toml_filled_from_manifest_base(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        # Partial ecc.toml: only [design] frequency — everything else from base.
        (project_dir / "ecc.toml").write_text(
            '[design]\nfrequency_mhz = 200.0\n\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        kwargs = flow_mocks.capture["create_kwargs"]
        assert kwargs["pdk"] == "ics55"
        assert kwargs["directory"] == str(project_dir / "ws_0001")
        parameters = kwargs["parameters"]
        assert parameters["top_module"] == "gcd"  # from manifest base
        assert parameters["clock"] == "clk"  # from manifest base
        assert parameters["frequency_max"] == 200.0  # ecc.toml wins

    def test_project_flow_preset_outranks_manifest_entry_range(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(
            project_dir,
            [
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(project_dir / "ws_0001"),
                    "start_step": "Place",
                    "end_step": "Route",
                }
            ],
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rcx"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        kwargs = flow_mocks.capture["create_kwargs"]
        assert kwargs["flow_config"] is None  # preset drives, not the entry range

    def test_diverging_layers_emit_warning(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "other_top"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        assert "top_module" in warnings[0]["keys"]
