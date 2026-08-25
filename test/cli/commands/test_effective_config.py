import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main

_HYBRID_TOML = (
    '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\n'
    'clock_port = "clk"\nfrequency_mhz = 100.0\n'
    '\n[pdk]\nname = "ics55"\nroot = "{ROOT}"\n'
    '\n[flow]\npreset = "rtl2gds"\n'
)


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

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        filelist = flow_mocks.capture["create_kwargs"]["input_filelist"]
        lines = Path(filelist).read_text().splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("rtl/gcd.v")
        assert lines[1].endswith("rtl/b.v")

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


class TestDivergenceProjectionFields:
    def _hybrid(
        self, manifest_stubs, tmp_path, monkeypatch, toml_text, base_overrides=None, patch=None
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        base = {
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "parameters": {"design": "gcd", "frequency_max": 100, "max_fanout": 20},
        }
        if base_overrides:
            base.update(base_overrides)
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        if patch:
            entry["parameter_patch"] = patch
        manifest_stubs.write(project_dir, [entry], base_design=base)
        (project_dir / "ecc.toml").write_text(toml_text.replace("{ROOT}", str(project_dir / "pdk")))
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        return project_dir

    def test_check_warns_on_name_rtl_frequency_and_patched_parameter(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            '[design]\nname = "other"\ntop = "gcd"\n'
            'rtl = ["rtl/other.v"]\nclock_port = "clk"\nfrequency_mhz = 250.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "{ROOT}"\n'
            '\n[flow]\npreset = "rtl2gds"\n\n[params.synth]\nmax_fanout = 32\n',
            patch={"max_fanout": {"from": 20, "to": 24}},
        )
        (project_dir / "rtl" / "other.v").write_text("module other; endmodule\n")

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        keys = warnings[0]["keys"]
        assert "design_name" in keys
        assert "rtl" in keys
        assert "frequency_max" in keys
        assert "max_fanout" in keys

    def test_run_warns_on_same_projection(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            '[design]\nname = "other"\ntop = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\nclock_port = "clk"\nfrequency_mhz = 250.0\n'
            '\n[pdk]\nname = "ics55"\nroot = "{ROOT}"\n'
            '\n[flow]\npreset = "rtl2gds"\n',
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        records = manifest_stubs.records()
        warnings = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert len(warnings) == 1
        keys = warnings[0]["keys"]
        assert "design_name" in keys
        assert "frequency_max" in keys


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


class TestExplicitEmptyStaysExplicit:
    """A key present in ecc.toml — even with an empty value — is never
    filled from the manifest layer: it stays explicit, fails validation,
    and participates in divergence reporting."""

    def _hybrid(self, manifest_stubs, tmp_path, monkeypatch, toml_text):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
        (project_dir / "ecc.toml").write_text(toml_text.replace("{ROOT}", str(project_dir / "pdk")))
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        for env_key in ("CHIPCOMPILER_ICS55_PDK_ROOT", "ICS55_PDK_ROOT"):
            monkeypatch.delenv(env_key, raising=False)
        return project_dir

    _CASES = [
        pytest.param(
            _HYBRID_TOML.replace('name = "gcd"', 'name = ""'),
            "design.name is required",
            id="empty-name",
        ),
        pytest.param(
            _HYBRID_TOML.replace('top = "gcd"', 'top = ""'),
            "design.top is required",
            id="empty-top",
        ),
        pytest.param(
            _HYBRID_TOML.replace('clock_port = "clk"', 'clock_port = ""'),
            "design.clock_port is required",
            id="empty-clock",
        ),
        pytest.param(
            _HYBRID_TOML.replace('rtl = ["rtl/gcd.v"]', "rtl = []"),
            "design.rtl must have at least one entry",
            id="empty-rtl",
        ),
        pytest.param(
            _HYBRID_TOML.replace('name = "ics55"', 'name = ""'),
            "pdk.name is required",
            id="empty-pdk-name",
        ),
        pytest.param(
            _HYBRID_TOML.replace('root = "{ROOT}"', 'root = ""'),
            "pdk.root is required",
            id="empty-pdk-root",
        ),
        pytest.param(
            _HYBRID_TOML.replace('preset = "rtl2gds"', 'preset = ""'),
            "flow.preset is required",
            id="empty-preset",
        ),
    ]

    @pytest.mark.parametrize("toml_text,expected", _CASES)
    def test_check_explicit_empty_fails(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, toml_text, expected
    ):
        project_dir = self._hybrid(manifest_stubs, tmp_path, monkeypatch, toml_text)

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert expected in reasons

    @pytest.mark.parametrize("toml_text,expected", _CASES)
    def test_run_explicit_empty_fails_before_mutation(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, flow_mocks, toml_text, expected
    ):
        project_dir = self._hybrid(manifest_stubs, tmp_path, monkeypatch, toml_text)

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc != 0
        reasons = "\n".join(r.get("reason", "") for r in manifest_stubs.records())
        assert expected in reasons
        assert flow_mocks.capture["create_kwargs"] is None

    def test_check_explicit_empty_pdk_root_diverges_with_env_root(
        self, manifest_stubs, tmp_path, capsys, monkeypatch
    ):
        # An explicit empty root resolves through the env fallback (valid
        # here) — the explicit override must surface as a divergence, not
        # be hidden by the emptiness skip.
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            _HYBRID_TOML.replace('root = "{ROOT}"', 'root = ""'),
        )
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(project_dir / "pdk"))

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = [
            r for r in manifest_stubs.records() if r.get("warning") == "config_layer_diverged"
        ]
        assert len(warnings) == 1
        assert "pdk_root" in warnings[0]["keys"]


class TestLowerLayerDivergence:
    """The divergence projection covers every layerable key: a present-but-
    falsy lower-layer frequency and the entry's declared flow range both
    participate; equivalent layers never warn."""

    def _hybrid(self, manifest_stubs, tmp_path, monkeypatch, *, base_parameters, entry_range):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        entry["start_step"], entry["end_step"] = entry_range
        manifest_stubs.write(
            project_dir,
            [entry],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": base_parameters,
            },
        )
        (project_dir / "ecc.toml").write_text(
            _HYBRID_TOML.replace("{ROOT}", str(project_dir / "pdk"))
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        return project_dir

    @staticmethod
    def _divergences(records):
        return [r for r in records if r.get("warning") == "config_layer_diverged"]

    def test_check_warns_on_zero_lower_frequency(
        self, manifest_stubs, tmp_path, capsys, monkeypatch
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 0},
            entry_range=("Synth", "Filler"),
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = self._divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "frequency_max" in warnings[0]["keys"]

    def test_run_warns_on_zero_lower_frequency(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, flow_mocks
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 0},
            entry_range=("Synth", "Filler"),
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = self._divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "frequency_max" in warnings[0]["keys"]

    def test_check_warns_on_different_flow_range(
        self, manifest_stubs, tmp_path, capsys, monkeypatch
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 100},
            entry_range=("Place", "Route"),
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = self._divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "flow" in warnings[0]["keys"]

    def test_run_warns_on_different_flow_range(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, flow_mocks
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 100},
            entry_range=("Place", "Route"),
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = self._divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "flow" in warnings[0]["keys"]

    def test_check_equivalent_flow_range_stays_silent(
        self, manifest_stubs, tmp_path, capsys, monkeypatch
    ):
        # rtl2gds maps to (Synth, Filler) — the same range the entry declares.
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 100},
            entry_range=("Synth", "Filler"),
        )

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert self._divergences(manifest_stubs.records()) == []

    def test_run_equivalent_flow_range_stays_silent(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, flow_mocks
    ):
        project_dir = self._hybrid(
            manifest_stubs,
            tmp_path,
            monkeypatch,
            base_parameters={"design": "gcd", "frequency_max": 100},
            entry_range=("Synth", "Filler"),
        )

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert self._divergences(manifest_stubs.records()) == []
