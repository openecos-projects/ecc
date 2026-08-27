import pytest

from chipcompiler.cli import main as cli_main

_HYBRID_TOML = (
    '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\n'
    'clock_port = "clk"\nfrequency_mhz = 100.0\n'
    '\n[pdk]\nname = "ics55"\nroot = "{ROOT}"\n'
    '\n[flow]\npreset = "rtl2gds"\n'
)


def _divergences(records):
    return [r for r in records if r.get("warning") == "config_layer_diverged"]


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
        warnings = _divergences(manifest_stubs.records())
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
        warnings = _divergences(manifest_stubs.records())
        assert len(warnings) == 1
        keys = warnings[0]["keys"]
        assert "design_name" in keys
        assert "frequency_max" in keys


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
        warnings = _divergences(manifest_stubs.records())
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
        warnings = _divergences(manifest_stubs.records())
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
        warnings = _divergences(manifest_stubs.records())
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
        warnings = _divergences(manifest_stubs.records())
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
        warnings = _divergences(manifest_stubs.records())
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
        assert _divergences(manifest_stubs.records()) == []

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
        assert _divergences(manifest_stubs.records()) == []


class TestOrderedRtlDivergence:
    """RTL comparison is order-faithful: source order is execution
    significant, so a reordered list diverges; the same order never warns."""

    def _hybrid(self, manifest_stubs, tmp_path, monkeypatch, toml_rtl):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        entry["start_step"], entry["end_step"] = "Synth", "Filler"
        manifest_stubs.write(
            project_dir,
            [entry],
            base_design={
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v", "rtl/b.v"],
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
        )
        (project_dir / "rtl" / "b.v").write_text("module b; endmodule\n")
        (project_dir / "ecc.toml").write_text(
            _HYBRID_TOML.replace('rtl = ["rtl/gcd.v"]', f"rtl = [{toml_rtl}]").replace(
                "{ROOT}", str(project_dir / "pdk")
            )
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        return project_dir

    def test_check_warns_on_reordered_rtl(self, manifest_stubs, tmp_path, capsys, monkeypatch):
        project_dir = self._hybrid(manifest_stubs, tmp_path, monkeypatch, '"rtl/b.v", "rtl/gcd.v"')

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = _divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "rtl" in warnings[0]["keys"]

    def test_run_warns_on_reordered_rtl(
        self, manifest_stubs, tmp_path, capsys, monkeypatch, flow_mocks
    ):
        project_dir = self._hybrid(manifest_stubs, tmp_path, monkeypatch, '"rtl/b.v", "rtl/gcd.v"')

        rc = cli_main.run(["run", "--project", str(project_dir), "--json"])

        assert rc == 0
        warnings = _divergences(manifest_stubs.records())
        assert len(warnings) == 1
        assert "rtl" in warnings[0]["keys"]

    def test_same_order_stays_silent(self, manifest_stubs, tmp_path, capsys, monkeypatch):
        project_dir = self._hybrid(manifest_stubs, tmp_path, monkeypatch, '"rtl/gcd.v", "rtl/b.v"')

        rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

        assert rc == 0
        assert _divergences(manifest_stubs.records()) == []


class TestConfigResolvedManifestLayering:
    """ecc config --resolved shows the EFFECTIVE config: the same manifest
    layering check/run resolve, with source labels following the layers."""

    def _records_by_key(self, records):
        return {r["config"]: r for r in records if r.get("scope") == "project" and "resolved" in r}

    def test_manifest_only_project_shows_layered_config(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        manifest_stubs.write(project_dir, [entry])
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir), "--json"])

        assert rc == 0
        by_key = self._records_by_key(manifest_stubs.records())
        assert by_key["design.name"]["value"] == "gcd"
        assert by_key["design.name"]["source"] == "project.json"
        assert by_key["design.top"]["source"] == "project.json"
        assert by_key["design.rtl.0"]["source"] == "project.json"
        # The selected entry's range is the flow target, not a preset.
        assert by_key["flow.start"] == {
            "config": "flow.start",
            "scope": "project",
            "value": "Synth",
            "resolved": "Synth",
            "source": "project.json",
            "inspect": by_key["flow.start"]["inspect"],
        }
        assert by_key["flow.end"]["value"] == "Harden"
        assert "flow.preset" not in by_key

    def test_hybrid_project_labels_explicit_and_filled_sources(
        self, tmp_path, capsys, monkeypatch, manifest_stubs
    ):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        entry = manifest_stubs.entry(project_dir, "ws_0001")
        manifest_stubs.write(project_dir, [entry])
        (project_dir / "ecc.toml").write_text('[design]\nname = "other"\n')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir), "--json"])

        assert rc == 0
        by_key = self._records_by_key(manifest_stubs.records())
        assert by_key["design.name"]["value"] == "other"
        assert by_key["design.name"]["source"] == "ecc.toml"
        assert by_key["design.top"]["value"] == "gcd"
        assert by_key["design.top"]["source"] == "project.json"
        assert by_key["flow.start"]["source"] == "project.json"


def test_check_tolerates_huge_manifest_frequency(tmp_path, capsys, manifest_stubs):
    """A huge JSON integer frequency_max overflows float(); it degrades to
    the invalid-frequency config error, never a traceback."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    entry = manifest_stubs.entry(project_dir, "ws_0001")
    manifest_stubs.write(
        project_dir,
        [entry],
        base_design={
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "parameters": {"design": "gcd", "frequency_max": 10**400},
        },
    )

    rc = cli_main.run(["check", "--project", str(project_dir), "--json"])

    assert rc != 0
    records = manifest_stubs.records()
    assert any("frequency" in str(r.get("reason", "")) for r in records)


class TestSetDivergence:
    def test_run_warns_when_set_overrides_a_different_lower_value(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
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
                "parameters": {"design": "gcd", "frequency_max": 100, "max_fanout": 20},
            },
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(
            ["run", "--project", str(project_dir), "--set", "synth.max_fanout=32", "--json"]
        )

        assert rc == 0
        records = manifest_stubs.records()
        (warning,) = [r for r in records if r.get("warning") == "config_layer_diverged"]
        assert "max_fanout" in warning["keys"]
        assert "--set" in warning["reason"]

    def test_run_quiet_when_set_restates_the_lower_value(
        self, tmp_path, capsys, monkeypatch, flow_mocks, manifest_stubs
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
                "parameters": {"design": "gcd", "frequency_max": 100, "max_fanout": 20},
            },
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(
            ["run", "--project", str(project_dir), "--set", "synth.max_fanout=20", "--json"]
        )

        assert rc == 0
        assert not [
            r for r in manifest_stubs.records() if r.get("warning") == "config_layer_diverged"
        ]
