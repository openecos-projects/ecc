import json
import os
from pathlib import Path

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
        assert entry["end_step"] == "PostRouteLEC"
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

        rc = cli_main.run(["run", "--project", project_dir, "--set", "cts.max_fanout=16", "--json"])

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

    def test_virgin_run_fails_manifest_invalid_when_manifest_path_is_a_directory(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs
    ):
        project_dir = create_cli_project()
        # A directory sitting at the project.json path is PRESENT but not a
        # manifest: the project classifies as manifest and fails loud, never
        # a silent virgin demotion.
        os.mkdir(os.path.join(project_dir, "project.json"))

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        records = manifest_stubs.records()
        assert any(r.get("error") == "manifest_invalid" for r in records)
        assert flow_mocks.capture["create_kwargs"] is None

    def test_run_rejects_canonical_alias_of_a_declared_symlinked_workspace(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs
    ):
        """The canonical target name of a declared symlinked workspace is
        not a selector: --run-id actual must not resume (or overwrite) the
        workspace declared as linked."""
        project_dir = create_cli_project()
        actual = Path(project_dir) / "actual"
        actual.mkdir()
        (Path(project_dir) / "linked").symlink_to(actual)
        manifest_stubs.write(
            Path(project_dir),
            [
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(Path(project_dir) / "linked"),
                    "status": "success",
                }
            ],
        )

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "actual", "--json"])

        assert rc != 0
        records = manifest_stubs.records()
        (failure,) = [r for r in records if r.get("error") == "workspace_not_declared"]
        assert "ws_0001" in failure["reason"]
        assert flow_mocks.capture["create_kwargs"] is None

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

    def test_virgin_run_does_not_bind_to_a_same_id_winner_at_another_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks, manifest_stubs, monkeypatch
    ):
        project_dir = create_cli_project()

        def losing_write(project_dir_arg, document):
            # The winning manifest declares our run id at ANOTHER path:
            # continuing is fine, writing our status into it is not.
            manifest_stubs.write(
                Path(project_dir_arg),
                [
                    {
                        "workspace_id": "default",
                        "workspace_path": str(Path(project_dir_arg) / "other"),
                        "status": "running",
                    }
                ],
            )
            return False

        monkeypatch.setattr(
            "chipcompiler.cli.project.manifest.write_manifest_if_absent", losing_write
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert any(r.get("warning") == "manifest_generation_failed" for r in records)
        winner = json.loads((Path(project_dir) / "project.json").read_text())
        # Our run's success was never written into the other path's entry.
        assert winner["workspaces"][0]["status"] == "running"


class TestManifestRunCoercion:
    """Manifest parameter values reach create_workspace type-coerced; keys an
    ecc.toml/--set override actually replaces are skipped so the higher layer
    wins even when the manifest value is invalid."""

    def test_run_coerced_bool_reaches_create_workspace(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"design": "gcd", "frequency_max": 100, "run_analysis": "false"},
            },
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["run_analysis"] is False

    def test_run_set_overrides_invalid_manifest_bool(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"design": "gcd", "frequency_max": 100, "run_analysis": "maybe"},
            },
        )

        rc = cli_main.run(
            ["run", "--project", str(project_dir), "--set", "flow.run_analysis=false", "--json"]
        )

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["run_analysis"] is False

    def test_run_explicit_design_frequency_overrides_invalid_manifest_frequency(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"design": "gcd", "frequency_max": "abc"},
            },
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\nclock_port = "clk"\n'
            "frequency_mhz = 100.0\n"
            '\n[pdk]\nname = "ics55"\nroot = "'
            + str(project_dir / "pdk")
            + '"\n\n[flow]\npreset = "rtl2gds"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["frequency_max"] == 100.0

    def test_run_params_override_supersedes_invalid_manifest_fanout(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"design": "gcd", "frequency_max": 100, "max_fanout": "xyz"},
            },
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\nclock_port = "clk"\n'
            '\n[pdk]\nname = "ics55"\nroot = "'
            + str(project_dir / "pdk")
            + '"\n\n[flow]\npreset = "rtl2gds"\n\n[params.cts]\nmax_fanout = 20\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["max_fanout"] == 20


class TestFreshRunCoercionCleanup:
    """Defense-in-depth for the run preparation itself: a coercion failure
    past handler validation must not strand the freshly created run target,
    and a target this process does not own must survive untouched."""

    @staticmethod
    def _config(tmp_path, rtl):
        from chipcompiler.cli.project.config import ProjectConfig

        return ProjectConfig(
            design_name="gcd",
            design_top="gcd",
            design_rtl=rtl,
            design_clock_port="clk",
            design_frequency_mhz=100.0,
            pdk_name="ics55",
            pdk_root=str(tmp_path / "pdk"),
            flow_preset="rtl2gds",
            project_dir=str(tmp_path),
            manifest_parameters={"run_analysis": "maybe"},
        )

    @staticmethod
    def _execute(tmp_path, cfg, monkeypatch, owns_target):
        from types import SimpleNamespace

        from chipcompiler.cli.project import run_prepare

        materializations = []
        monkeypatch.setattr(
            run_prepare,
            "_materialize_rtl_filelist",
            lambda cfg: materializations.append(cfg) or "filelist",
        )
        run_dir = tmp_path / "ws_bad"
        run_dir.mkdir()
        (run_dir / "marker.txt").write_text("keep")
        result = run_prepare.execute_fresh_run(
            SimpleNamespace(),
            SimpleNamespace(project=None, project_dir=str(tmp_path)),
            cfg,
            str(run_dir),
            "ws_bad",
            {},
            None,
            "manifest",
            [],
            workspace_registered=False,
            owns_target=owns_target,
        )
        return result, run_dir, materializations

    def test_owned_target_cleaned_up_on_coercion_failure(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, ["rtl/a.v", "rtl/b.v"])

        result, run_dir, materializations = self._execute(
            tmp_path, cfg, monkeypatch, owns_target=True
        )

        assert result.exit_code == 1
        assert [r["error"] for r in result.records] == ["config_error"]
        assert "expected bool for flow.run_analysis" in result.records[0]["reason"]
        assert not run_dir.exists()
        # Materialization never ran, so no ecc-rtl-* temp dirs can leak.
        assert materializations == []

    def test_foreign_target_preserved_on_coercion_failure(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, ["rtl/a.v"])

        result, run_dir, _ = self._execute(tmp_path, cfg, monkeypatch, owns_target=False)

        assert result.exit_code == 1
        assert run_dir.exists()
        assert (run_dir / "marker.txt").read_text() == "keep"
