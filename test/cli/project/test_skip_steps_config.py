"""skip_steps configuration surface: project.json, ecc.toml, precedence.

One home for the config-layer tests of the skip policy: manifest parsing
and raw round-trip, ecc.toml parsing and validation, the shared precedence
(an explicit ecc.toml declaration wins over the project.json base entry,
like every other key), the shadow warning when both surfaces declare
different policies, and the materialized default in generated projects.
"""

import json

import pytest

from chipcompiler.cli.project.config import load_project_config, validate_project_config
from chipcompiler.cli.project.effective_config import (
    declared_skip_steps,
    skip_steps_shadow_warning,
)
from chipcompiler.cli.project.manifest import ManifestError, load_manifest
from chipcompiler.cli.project.manifest_write import write_back_workspace_status


def _write_manifest(project_dir, workspaces):
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "workspaces": workspaces,
    }
    (project_dir / "project.json").write_text(json.dumps(document))


def _workspace(project_dir, **extra):
    entry = {
        "workspace_id": "ws_0001",
        "workspace_path": str(project_dir / "ws_0001"),
        "status": "not_started",
    }
    entry.update(extra)
    return entry


class TestManifestSkipSteps:
    def test_absent_key_loads_as_none(self, tmp_path):
        _write_manifest(tmp_path, [_workspace(tmp_path)])

        (entry,) = load_manifest(str(tmp_path)).workspaces

        assert entry.skip_steps is None

    def test_declared_spelling_is_kept_verbatim(self, tmp_path):
        _write_manifest(tmp_path, [_workspace(tmp_path, skip_steps=["LEC", "lec", "postlec"])])

        (entry,) = load_manifest(str(tmp_path)).workspaces

        # One normalizer exists (the resolver); the manifest stores the
        # declared spelling and only checks its validity.
        assert entry.skip_steps == ("LEC", "lec", "postlec")

    def test_explicit_empty_list_is_distinct_from_absent(self, tmp_path):
        _write_manifest(tmp_path, [_workspace(tmp_path, skip_steps=[])])

        (entry,) = load_manifest(str(tmp_path)).workspaces

        assert entry.skip_steps == ()

    @pytest.mark.parametrize(
        "value",
        [
            "lec",
            None,
            [1],
            ["route"],
            ["bogus"],
        ],
    )
    def test_invalid_value_fails_the_whole_manifest_load(self, tmp_path, value):
        _write_manifest(tmp_path, [_workspace(tmp_path, skip_steps=value)])

        with pytest.raises(ManifestError, match=r"workspaces\[0\].*skip_steps"):
            load_manifest(str(tmp_path))

    def test_status_write_back_preserves_raw_spelling(self, tmp_path):
        _write_manifest(tmp_path, [_workspace(tmp_path, skip_steps=["LEC", "lec"])])

        assert write_back_workspace_status(str(tmp_path), "ws_0001", "running")

        document = json.loads((tmp_path / "project.json").read_text())
        assert document["workspaces"][0]["skip_steps"] == ["LEC", "lec"]
        assert document["workspaces"][0]["status"] == "running"


class TestEccTomlSkipSteps:
    def _config(self, tmp_path, flow_extra):
        (tmp_path / "ecc.toml").write_text(
            "[design]\n"
            'name = "gcd"\n'
            'top = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\n'
            'clock_port = "clk"\n'
            "frequency_mhz = 100.0\n"
            "\n[flow]\n"
            'preset = "rtl2gds"\n' + flow_extra
        )
        return load_project_config(str(tmp_path / "ecc.toml"))

    def test_absent_key_parses_as_none(self, tmp_path):
        cfg = self._config(tmp_path, "")

        assert cfg.flow_skip_steps is None

    def test_declared_list_is_kept_verbatim(self, tmp_path):
        cfg = self._config(tmp_path, 'skip_steps = ["TimingOpt", "lec"]\n')

        assert cfg.flow_skip_steps == ["TimingOpt", "lec"]

    @pytest.mark.parametrize(
        "flow_extra",
        [
            'skip_steps = "lec"\n',
            "skip_steps = 3\n",
            "skip_steps = [1]\n",
            'skip_steps = ["route"]\n',
        ],
    )
    def test_invalid_value_is_a_config_error(self, tmp_path, flow_extra):
        cfg = self._config(tmp_path, flow_extra)

        assert any("skip_steps" in err for err in validate_project_config(cfg))


class TestSkipStepsPrecedence:
    def _entry_and_cfg(self, tmp_path, manifest_skip=None, toml_skip=None):
        _write_manifest(
            tmp_path,
            [
                _workspace(tmp_path)
                if manifest_skip == "absent"
                else _workspace(
                    tmp_path,
                    skip_steps=[] if manifest_skip == "empty" else manifest_skip,
                )
            ],
        )
        entry = load_manifest(str(tmp_path)).workspaces[0]
        toml_flow = "" if toml_skip == "absent" else f"skip_steps = {toml_skip!r}\n"
        (tmp_path / "ecc.toml").write_text(
            "[design]\n"
            'name = "gcd"\n'
            'top = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\n'
            'clock_port = "clk"\n'
            "frequency_mhz = 100.0\n"
            "\n[flow]\n"
            'preset = "rtl2gds"\n' + toml_flow.replace("'", '"')
        )
        cfg = load_project_config(str(tmp_path / "ecc.toml"))
        return entry, cfg

    def test_ecc_toml_wins_over_project_json(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["TimingOpt"], toml_skip=["lec"])

        assert declared_skip_steps(entry, cfg) == ["lec"]

    def test_ecc_toml_explicit_empty_wins_over_project_json(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["lec"], toml_skip=[])

        assert declared_skip_steps(entry, cfg) == []

    def test_project_json_applies_when_ecc_toml_lacks_the_key(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["lec"], toml_skip="absent")

        assert declared_skip_steps(entry, cfg) == ["lec"]

    def test_code_default_when_both_surfaces_are_absent(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip="absent", toml_skip="absent")

        assert declared_skip_steps(entry, cfg) is None


class TestSkipStepsShadowWarning:
    def _entry_and_cfg(self, tmp_path, manifest_skip, toml_skip):
        _write_manifest(
            tmp_path,
            [_workspace(tmp_path, skip_steps=[] if manifest_skip == "empty" else manifest_skip)],
        )
        entry = load_manifest(str(tmp_path)).workspaces[0]
        toml_flow = "" if toml_skip == "absent" else f"skip_steps = {toml_skip!r}\n"
        (tmp_path / "ecc.toml").write_text(
            "[design]\n"
            'name = "gcd"\n'
            'top = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\n'
            'clock_port = "clk"\n'
            "frequency_mhz = 100.0\n"
            "\n[flow]\n"
            'preset = "rtl2gds"\n' + toml_flow.replace("'", '"')
        )
        cfg = load_project_config(str(tmp_path / "ecc.toml"))
        return entry, cfg

    def test_warning_when_ecc_toml_shadows_a_different_manifest_entry(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["TimingOpt"], toml_skip=["lec"])

        warning = skip_steps_shadow_warning(entry, cfg)

        assert warning is not None
        assert warning["warning"] == "skip_steps_shadowed"
        assert warning["effective_source"] == "ecc.toml"
        assert warning["shadowed_source"] == "project.json"

    def test_no_warning_when_the_policies_agree(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["LEC", "lec"], toml_skip=["lec"])

        assert skip_steps_shadow_warning(entry, cfg) is None

    def test_no_warning_without_an_ecc_toml_declaration(self, tmp_path):
        entry, cfg = self._entry_and_cfg(tmp_path, manifest_skip=["lec"], toml_skip="absent")

        assert skip_steps_shadow_warning(entry, cfg) is None

    def test_no_warning_without_a_manifest_entry(self, tmp_path):
        _write_manifest(tmp_path, [_workspace(tmp_path)])
        entry = load_manifest(str(tmp_path)).workspaces[0]
        (tmp_path / "ecc.toml").write_text(
            "[design]\n"
            'name = "gcd"\n'
            'top = "gcd"\n'
            'rtl = ["rtl/gcd.v"]\n'
            'clock_port = "clk"\n'
            "frequency_mhz = 100.0\n"
            "\n[flow]\n"
            'preset = "rtl2gds"\nskip_steps = ["lec"]\n'
        )
        cfg = load_project_config(str(tmp_path / "ecc.toml"))

        assert skip_steps_shadow_warning(entry, cfg) is None


def test_init_materializes_the_default_skip_into_generated_ecc_toml(tmp_path):
    from chipcompiler.cli import main as cli_main

    rc = cli_main.run(["init", str(tmp_path / "gcd")])

    assert rc == 0
    toml = (tmp_path / "gcd" / "ecc.toml").read_text()
    assert 'skip_steps = ["lec"]' in toml
    assert "LEC is skipped by default; clear the list to enable it." in toml


def test_pre_register_materializes_declared_skip_steps(tmp_path, monkeypatch):
    """A fresh manifest registration records the workspace's declared
    skip policy on the entry (declared spelling preserved)."""
    from chipcompiler.cli.project.config import load_project_config
    from chipcompiler.cli.project.manifest_write import pre_register_workspace

    (tmp_path / "ecc.toml").write_text(
        "[design]\n"
        'name = "gcd"\n'
        'top = "gcd"\n'
        'rtl = ["rtl/gcd.v"]\n'
        'clock_port = "clk"\n'
        "frequency_mhz = 100.0\n"
        "\n[pdk]\n"
        'name = "ics55"\n'
        'root = "/pdk"\n'
        "\n[flow]\n"
        'preset = "rtl2gds"\n'
    )
    cfg = load_project_config(str(tmp_path / "ecc.toml"))

    outcome = pre_register_workspace(
        str(tmp_path),
        cfg=cfg,
        pdk_root="/pdk",
        workspace_id="ws_0001",
        workspace_path=str(tmp_path / "ws_0001"),
        flow_config={"skip_steps": ["TimingOpt"]},
    )

    assert outcome == "registered"
    (entry,) = load_manifest(str(tmp_path)).workspaces
    assert entry.skip_steps == ("TimingOpt",)


class TestManifestSkipBoundary:
    def test_skipped_manifest_boundary_fails_the_load(self, tmp_path):
        _write_manifest(
            tmp_path,
            [_workspace(tmp_path, start_step="Synth", end_step="LEC", skip_steps=["LEC"])],
        )

        with pytest.raises(ManifestError, match="cannot bound the flow range"):
            load_manifest(str(tmp_path))

    def test_skipped_step_inside_the_manifest_range_is_fine(self, tmp_path):
        _write_manifest(
            tmp_path,
            [
                _workspace(
                    tmp_path,
                    start_step="Synth",
                    end_step="PreFloorplan",
                    skip_steps=["LEC"],
                )
            ],
        )

        (entry,) = load_manifest(str(tmp_path)).workspaces

        assert entry.skip_steps == ("LEC",)
