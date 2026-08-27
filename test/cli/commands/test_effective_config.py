import json
from pathlib import Path

from chipcompiler.cli import main as cli_main


class TestHybridManifestFallbacks:
    def test_flowless_ecc_toml_existing_run_uses_workspace_flow(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
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
        records = manifest_stubs.records()
        assert records[0]["status"] == "success"
        assert records[0]["no_op"] is True

    def test_multi_rtl_manifest_materializes_filelist(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir(exist_ok=True)
        (project_dir / "rtl" / "b.v").write_text("module b; endmodule\n")
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
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

        generated = {}
        from chipcompiler.cli.project import run_prepare

        original_materialize = run_prepare._materialize_rtl_filelist

        def capture_materialize(cfg):
            path = original_materialize(cfg)
            generated["content"] = Path(path).read_text()
            return path

        monkeypatch.setattr(run_prepare, "_materialize_rtl_filelist", capture_materialize)

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        lines = generated["content"].splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("rtl/gcd.v")
        assert lines[1].endswith("rtl/b.v")
        # The generated temporary filelist is cleaned up after creation.
        filelist = flow_mocks.capture["create_kwargs"]["input_filelist"]
        assert not Path(filelist).exists()

    def test_check_reports_layer_divergence(
        self, tmp_path, capsys, monkeypatch, minimal_ics55_pdk_factory, manifest_stubs
    ):
        minimal_ics55_pdk_factory(tmp_path / "ics55_unused")
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
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
        records = manifest_stubs.records()
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        assert "top_module" in warnings[0]["keys"]


class TestCheckHybridEffectiveValidation:
    def test_check_flowless_partial_hybrid_passes(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        # Partial ecc.toml: only frequency — the rest comes from the manifest.
        (project_dir / "ecc.toml").write_text("[design]\nfrequency_mhz = 200.0\n")
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"

    def test_check_multi_rtl_manifest_passes(self, tmp_path, capsys, monkeypatch, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()
        (project_dir / "rtl" / "b.v").write_text("module b; endmodule\n")
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v", "rtl/b.v"],
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
        )
        (project_dir / "ecc.toml").write_text("[design]\nfrequency_mhz = 100.0\n")
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"


class TestEffectiveConfigValidation:
    """The shared effective-config path: semantic check validation, per-source
    RTL checks, origin_verilog fallback, and pre-mutation flow-target errors."""

    def _manifest_base(self, project_dir, **overrides):
        base = {
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "parameters": {"design": "gcd", "frequency_max": 100},
        }
        base.update(overrides)
        return base

    def test_manifest_only_check_fails_semantic_validation(self, tmp_path, capsys, manifest_stubs):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # Missing top/clock and an empty PDK root must fail `ecc check` for a
        # manifest-only project, not pass silently.
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design=self._manifest_base(project_dir, top_module="", clock=""),
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "design.top is required" in reasons
        assert "design.clock_port is required" in reasons
        assert "PDK validation failed" in reasons

    def test_manifest_only_check_validates_every_rtl_source(
        self, tmp_path, capsys, minimal_ics55_pdk_factory, manifest_stubs
    ):
        for missing_position in (0, 1):
            project_dir = tmp_path / f"proj{missing_position}"
            project_dir.mkdir()
            rtl_list = ["rtl/gcd.v", "rtl/b.v"]
            manifest_stubs.write(
                project_dir,
                [manifest_stubs.entry(project_dir, "ws_0001")],
                base_design=self._manifest_base(project_dir, rtl_list=rtl_list),
            )
            minimal_ics55_pdk_factory(project_dir / "pdk")
            missing = rtl_list[missing_position]
            present = rtl_list[1 - missing_position]
            (project_dir / present).write_text("module b; endmodule\n")
            if missing_position == 0:
                # _write_manifest created rtl/gcd.v; remove it so the FIRST
                # declared source is the missing one.
                (project_dir / "rtl" / "gcd.v").unlink()

            rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

            assert rc != 0
            reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
            assert f"rtl path does not exist: {missing}" in reasons

    def test_hybrid_check_falls_back_to_origin_verilog(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "src").mkdir()
        (project_dir / "src" / "gcd.v").write_text("module gcd(input clk); endmodule\n")
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design=self._manifest_base(project_dir, rtl_list=[], origin_verilog="src/gcd.v"),
        )
        # Hybrid ecc.toml declares no rtl: the manifest origin_verilog fills it.
        (project_dir / "ecc.toml").write_text("[design]\nfrequency_mhz = 100.0\n")
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"
        rtl_records = [r for r in records if r.get("check") == "rtl"]
        assert rtl_records[0]["path"] == "src/gcd.v"

    def test_flowless_undeclared_run_fails_before_any_mutation(
        self, tmp_path, capsys, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        # Hybrid ecc.toml WITHOUT [flow]; the run id is NOT declared in the
        # manifest, so no entry range can seed the flow target either.
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--run-id", "sweep1", "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "no flow target" in reasons
        assert not (project_dir / "sweep1").exists()
        assert flow_mocks.capture["create_kwargs"] is None

    def test_check_warns_on_gui_geometry_divergence(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # GUI-flat alias in the manifest, canonical [params] override in
        # ecc.toml: one canonical projection must still match them.
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design=self._manifest_base(
                project_dir,
                parameters={"design": "gcd", "frequency_max": 100, "utilitization": 0.6},
            ),
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
            "\n[params.floorplan]\ncore_util = 0.55\n"
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = [
            r for r in manifest_stubs.records() if r.get("warning") == "config_layer_diverged"
        ]
        assert len(warnings) == 1
        assert "core.utilitization" in warnings[0]["keys"]

    def test_equivalent_path_spellings_produce_no_divergence(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        # Manifest spells pdk_root absolute and rtl relative; ecc.toml spells
        # pdk_root relative and rtl absolute. Same files: no false warnings.
        # The entry declares the same range rtl2gds maps to, isolating the
        # path-spelling comparison.
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        entry["start_step"], entry["end_step"] = "Synth", "Filler"
        manifest_stubs.write(project_dir, [entry])
        (project_dir / "ecc.toml").write_text(
            '[design]\nname = "gcd"\ntop = "gcd"\n'
            'rtl = ["' + str(project_dir / "rtl" / "gcd.v") + '"]\n'
            'clock_port = "clk"\nfrequency_mhz = 100.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "pdk"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"
        assert all(r.get("warning") != "config_layer_diverged" for r in records)


class TestHybridFrequencyProvenance:
    """An absent ecc.toml frequency fills from the manifest layer; an explicit
    (even invalid) ecc.toml frequency stays explicit and faces validation."""

    def _hybrid(self, manifest_stubs, tmp_path, monkeypatch, design_lines, frequency_max=200):
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
                "parameters": {"design": "gcd", "frequency_max": frequency_max},
            },
        )
        (project_dir / "ecc.toml").write_text(
            "[design]\n" + design_lines + "\n"
            '\n[pdk]\nname = "ics55"\nroot = "' + str(project_dir / "pdk") + '"\n'
            '\n[flow]\npreset = "rtl2gds"\n'
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        return project_dir

    _FULL_DESIGN_NO_FREQUENCY = 'name = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\nclock_port = "clk"'

    def test_check_fills_absent_frequency_from_manifest(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs, tmp_path, monkeypatch, self._FULL_DESIGN_NO_FREQUENCY
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert manifest_stubs.records()[0]["status"] == "checked"

    def test_check_explicit_zero_frequency_still_fails(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            self._FULL_DESIGN_NO_FREQUENCY + "\nfrequency_mhz = 0",
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "design.frequency_mhz must be greater than 0" in reasons

    def test_run_fills_absent_frequency_from_manifest(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs, tmp_path, monkeypatch, self._FULL_DESIGN_NO_FREQUENCY
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["frequency_max"] == 200

    def test_run_explicit_zero_frequency_fails_before_mutation(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            self._FULL_DESIGN_NO_FREQUENCY + "\nfrequency_mhz = 0",
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "design.frequency_mhz must be greater than 0" in reasons
        assert flow_mocks.capture["create_kwargs"] is None

    def test_check_rejects_unreadable_ecc_toml_instead_of_manifest_fallback(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        """An existing but unreadable ecc.toml is the highest-precedence
        config: check must fail loud, not silently run on the manifest."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").write_text('[design]\nname = "gcd"\n')

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert any(r.get("error") == "config_error" for r in records)

    def test_check_rejects_symlink_loop_ecc_toml_instead_of_manifest_fallback(
        self, tmp_path, capsys, manifest_stubs
    ):
        """Discovery itself must not swallow the config: a symlink loop at
        ecc.toml is PRESENT but unreadable — config_error, not a silent
        manifest-only demotion."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").symlink_to("ecc.toml")

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert any(r.get("error") == "config_error" for r in records)

    def test_multi_rtl_manifest_expands_nested_filelists(
        self, tmp_path, capsys, flow_mocks, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()
        (project_dir / "rtl" / "a.v").write_text("module a; endmodule\n")
        (project_dir / "rtl" / "b.v").write_text("module b; endmodule\n")
        (project_dir / "rtl" / "nested.f").write_text("b.v\n")
        manifest_stubs.write(
            project_dir,
            [manifest_stubs.entry(project_dir, "ws_0001")],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/a.v", "rtl/nested.f"],
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
        )
        (project_dir / "ecc.toml").write_text(
            '[design]\nfrequency_mhz = 100.0\n\n[flow]\npreset = "rtl2gds"\n'
        )

        generated = {}
        from chipcompiler.cli.project import run_prepare

        original_materialize = run_prepare._materialize_rtl_filelist

        def capture_materialize(cfg):
            path = original_materialize(cfg)
            generated["content"] = Path(path).read_text()
            return path

        monkeypatch.setattr(run_prepare, "_materialize_rtl_filelist", capture_materialize)

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        lines = generated["content"].splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("rtl/a.v")
        assert lines[1].endswith("rtl/b.v")
        assert not any(line.endswith(".f") for line in lines)


def _write_manifest_project(
    manifest_stubs,
    tmp_path,
    monkeypatch,
    frequency_max,
    ecc_toml=None,
    extra_parameters=None,
):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    parameters = {"design": "gcd", "frequency_max": frequency_max}
    parameters.update(extra_parameters or {})
    manifest_stubs.write(
        project_dir,
        [manifest_stubs.entry(project_dir, "ws_0001")],
        base_design={
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "parameters": parameters,
        },
    )
    if ecc_toml is not None:
        (project_dir / "ecc.toml").write_text(ecc_toml)
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    return project_dir


class TestManifestParameterValidation:
    """Manifest-layer parameter values face the registry rules in the shared
    preflight (both `ecc check` and `ecc run`) — unless an explicit
    ecc.toml/--set key makes the value inert, in which case it surfaces as a
    divergence warning instead of an error."""

    def _hybrid_toml(self, project_dir, *, frequency: bool) -> str:
        design = '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\nclock_port = "clk"\n'
        if frequency:
            design += "frequency_mhz = 100.0\n"
        return (
            design
            + '\n[pdk]\nname = "ics55"\nroot = "'
            + str(project_dir / "pdk")
            + '"\n\n[flow]\npreset = "rtl2gds"\n'
        )

    def test_check_rejects_out_of_range_manifest_frequency(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = _write_manifest_project(manifest_stubs, tmp_path, monkeypatch, 99999)

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "project.json: value 99999 out of range" in reasons
        assert "design.frequency_mhz" in reasons

    def test_check_explicit_frequency_overrides_invalid_manifest_value(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        toml_text = self._hybrid_toml(project_dir, frequency=True)
        _write_manifest_project(manifest_stubs, tmp_path, monkeypatch, 99999, ecc_toml=toml_text)

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        assert records[0]["status"] == "checked"
        diverged = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert diverged and "frequency_max" in diverged[0]["keys"]

    def test_run_set_overrides_invalid_manifest_value(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        toml_text = self._hybrid_toml(project_dir, frequency=False)
        _write_manifest_project(manifest_stubs, tmp_path, monkeypatch, 99999, ecc_toml=toml_text)

        rc = cli_main.run(
            [
                "run",
                "--project",
                str(project_dir),
                "--set",
                "design.frequency_mhz=100",
                "--json",
            ]
        )

        assert rc == 0
        parameters = flow_mocks.capture["create_kwargs"]["parameters"]
        assert parameters["frequency_max"] == 100.0


class TestManifestFlatGeometryValidation:
    """Generated manifests hoist geometry to GUI-flat aliases (utilitization,
    margin, ...); validation must resolve the canonical projection, and raw
    values must satisfy the registry's type rules — not just its ranges."""

    def test_check_rejects_out_of_range_gui_flat_geometry(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = _write_manifest_project(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            100,
            extra_parameters={"utilitization": 5.0},
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "project.json: value 5.0 out of range [0.01, 1.0] for floorplan.core_util" in reasons

    def test_check_rejects_non_numeric_manifest_parameter(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = _write_manifest_project(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            100,
            extra_parameters={"max_fanout": "abc"},
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert "project.json: value 'abc' is not numeric for synth.max_fanout" in reasons

    def test_check_accepts_valid_gui_flat_geometry(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = _write_manifest_project(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            100,
            extra_parameters={"utilitization": 0.6, "aspect_ratio": 1.0, "margin": 2},
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert manifest_stubs.records()[0]["status"] == "checked"


class TestManifestResolvedConfigView:
    """`ecc config --resolved` presents manifest-layer parameters through the
    same canonical projection the run uses (GUI-flat aliases included)."""

    def test_config_resolved_shows_gui_flat_manifest_geometry(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
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
                "parameters": {"design": "gcd", "frequency_max": 100, "utilitization": 0.6},
            },
        )

        rc = cli_main.run(["config", "--resolved", "--json", "--project", str(project_dir)])

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        params = {r["key"]: r for r in data["records"] if r.get("kind") == "param"}
        assert params["floorplan.core_util"]["value"] == 0.6
        assert params["floorplan.core_util"]["source"] == "project.json"
