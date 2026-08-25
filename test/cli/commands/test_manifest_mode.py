import json
import os

from chipcompiler.cli import main as cli_main


def _write_manifest(project_dir, workspaces, **overrides):
    rtl = project_dir / "rtl" / "gcd.v"
    rtl.parent.mkdir(parents=True, exist_ok=True)
    rtl.write_text("module gcd(input clk); endmodule\n")
    (project_dir / "pdk").mkdir(exist_ok=True)
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "base_design": {
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "parameters": {"design": "gcd", "frequency_max": 100},
        },
        "workspaces": workspaces,
    }
    document.update(overrides)
    (project_dir / "project.json").write_text(json.dumps(document))


def _workspace_entry(project_dir, workspace_id, status="success"):
    return {
        "workspace_id": workspace_id,
        "workspace_path": str(project_dir / workspace_id),
        "status": status,
    }


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


class TestManifestRunDiscovery:
    def test_single_active_workspace_auto_selected(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        run_dir = project_dir / "ws_0001"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_run_id_selects_by_workspace_id_or_path_tail(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--run-id", "ws_0002", "--json"]
        )

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_multiple_workspaces_without_run_id_errors(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["kind"] == "error"
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]
        assert "ws_0002" in record["reason"]

    def test_nested_run_id_is_invalid_not_undeclared(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(
            ["status", "--project", str(project_dir), "--run-id", "sweeps/s1", "--json"]
        )

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "invalid_run_id"

    def test_absolute_run_id_is_invalid_not_undeclared(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["status", "--project", str(project_dir), "--run-id", "/tmp/x", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "invalid_run_id"

    def test_unknown_run_id_errors_with_declared_ids(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["status", "--project", str(project_dir), "--run-id", "nope", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "workspace_not_declared"
        assert "ws_0001" in record["reason"]

    def test_archived_workspace_not_auto_selected(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001", status="archived"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )
        run_dir = project_dir / "ws_0002"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text('{"steps": []}')

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert _records(capsys)[0]["workspace"] == str(run_dir)

    def test_invalid_manifest_errors(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("{broken")

        rc = cli_main.run(["status", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "manifest_invalid"


class TestManifestCheck:
    def test_check_reports_manifest_project(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        assert records[0]["status"] == "checked"
        assert records[0]["config"] == "project.json"


class TestLegacyHint:
    def test_check_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", "default"))

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1
        assert "ecc migrate" in hint[0]["migrate"]

    def test_check_no_hint_in_virgin_project(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_check_no_hint_in_manifest_project(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        assert all(r.get("warning") != "legacy_layout_detected" for r in records)

    def test_status_emits_legacy_hint_in_runs_project(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        hint = [r for r in records if r.get("warning") == "legacy_layout_detected"]
        assert len(hint) == 1


class TestParamManifestMode:
    def _manifest_project(self, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        return project_dir

    def test_param_list_requires_ecc_toml(self, tmp_path, capsys):
        project_dir = self._manifest_project(tmp_path)

        rc = cli_main.run(["param", "list", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "param_requires_ecc_toml"

    def test_param_set_requires_ecc_toml(self, tmp_path, capsys):
        project_dir = self._manifest_project(tmp_path)

        rc = cli_main.run(
            ["param", "set", "synth.max_fanout", "16", "--project", str(project_dir), "--json"]
        )

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "param_requires_ecc_toml"
        assert not (project_dir / "ecc.toml").exists()


class TestVirginFirstRun:
    def test_virgin_run_generates_manifest_at_root_layout(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "default")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        records = _records(capsys)
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
        assert manifest["base_design"]["pdk"] == "ics55"
        assert manifest["base_design"]["top_module"] == "gcd"
        assert manifest["base_design"]["clock"] == "clk"

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
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "sweeps/s1", "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "invalid_run_id"


class TestManifestRunCommand:
    def test_undeclared_run_id_creates_at_root_with_warning(self, tmp_path, capsys, flow_mocks):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["run", "--project", str(project_dir), "--run-id", "exp2", "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == str(project_dir / "exp2")
        records = _records(capsys)
        warning = [r for r in records if r.get("warning") == "workspace_not_registered"]
        assert len(warning) == 1
        # No manifest entry is added for undeclared runs.
        manifest = json.loads((project_dir / "project.json").read_text())
        assert [w["workspace_id"] for w in manifest["workspaces"]] == ["ws_0001"]

    def test_declared_workspace_run_writes_back_status(self, tmp_path, capsys, flow_mocks):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == str(project_dir / "ws_0001")
        manifest = json.loads((project_dir / "project.json").read_text())
        assert manifest["workspaces"][0]["status"] == "success"


class TestHybridLayering:
    def test_ecc_toml_overlays_manifest_base(self, tmp_path, capsys, flow_mocks):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [_workspace_entry(project_dir, "ws_0001")],
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
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
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
        (record,) = _records(capsys)
        assert record["error"] == "invalid_flow_json"


class TestCheckManifestSelection:
    def test_check_errors_when_workspace_selection_ambiguous(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
            project_dir,
            [
                _workspace_entry(project_dir, "ws_0001"),
                _workspace_entry(project_dir, "ws_0002"),
            ],
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "workspace_not_declared"

    def test_check_ok_with_single_workspace(self, tmp_path, capsys):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0


class TestHybridCheck:
    def test_hybrid_check_errors_on_ambiguous_selection(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        import json as _json

        (tmp_path / "gcd" / "project.json").write_text(
            _json.dumps(
                {
                    "schema_version": 1,
                    "design_name": "gcd",
                    "root_path": project_dir,
                    "workspaces": [
                        {"workspace_id": "ws_0001", "workspace_path": f"{project_dir}/ws_0001"},
                        {"workspace_id": "ws_0002", "workspace_path": f"{project_dir}/ws_0002"},
                    ],
                }
            )
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "workspace_not_declared"


class TestHybridFullLayering:
    def test_partial_ecc_toml_filled_from_manifest_base(
        self, tmp_path, capsys, flow_mocks, monkeypatch
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
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
        self, tmp_path, capsys, flow_mocks, monkeypatch
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(
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

    def test_diverging_layers_emit_warning(self, tmp_path, capsys, flow_mocks, monkeypatch):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "other_top"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        assert "top_module" in warnings[0]["keys"]


class TestHybridManifestFallbacks:
    def test_flowless_ecc_toml_existing_run_uses_workspace_flow(
        self, tmp_path, capsys, flow_mocks, monkeypatch
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        # Hybrid ecc.toml WITHOUT [flow].
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
        )
        # Existing workspace carrying its own [flow].
        run_dir = project_dir / "ws_0001"
        (run_dir / "home").mkdir(parents=True)
        (run_dir / "home" / "flow.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                    ]
                }
            )
        )
        from chipcompiler.data.workspace_config import save_workspace_config

        assert save_workspace_config(
            run_dir,
            {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
            {"start": "Synthesis", "end": "Synthesis"},
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        assert records[0]["status"] == "success"
        assert records[0]["no_op"] is True

    def test_multi_rtl_manifest_materializes_filelist(
        self, tmp_path, capsys, flow_mocks, monkeypatch
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir(exist_ok=True)
        (project_dir / "rtl" / "b.v").write_text("module b; endmodule\n")
        _write_manifest(
            project_dir,
            [_workspace_entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v", "rtl/b.v"],
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nfrequency_mhz = 100.0\n\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        filelist = flow_mocks.capture["create_kwargs"]["input_filelist"]
        from pathlib import Path as _P

        lines = _P(filelist).read_text().splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("rtl/gcd.v")
        assert lines[1].endswith("rtl/b.v")

    def test_check_reports_layer_divergence(
        self, tmp_path, capsys, monkeypatch, minimal_ics55_pdk_factory
    ):
        minimal_ics55_pdk_factory(tmp_path / "ics55_unused")
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _write_manifest(project_dir, [_workspace_entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "other_top"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = _records(capsys)
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        assert "top_module" in warnings[0]["keys"]
