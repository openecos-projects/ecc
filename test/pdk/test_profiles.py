"""Default selection must be exact, atomic and independent of project locks."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.commands.pdk.profiles import profiles_app
from chipcompiler.cli.project.config import ProjectConfig
from chipcompiler.cli.project.run_preflight import pdk_issues_for_config
from chipcompiler.pdk import profiles
from chipcompiler.pdk.documents import (
    EccAdaptation,
    ManagedConfiguration,
    PdkDescription,
    document_digest,
)
from chipcompiler.pdk.locking import bind_project, lock_workspace_inputs, read_lock
from chipcompiler.pdk.managed import (
    adopt_configuration,
    configuration_path,
    import_configuration,
    read_configuration,
)
from chipcompiler.pdk.manifest import DescriptorError, Resource, file_digest, load_descriptor


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    root = tmp_path / "pdk"
    root.mkdir()
    library = root / "cells.lib"
    library.write_text("library(test) {}\n")
    facts = PdkDescription(
        family_id="example",
        release="r1",
        resources={"lib": Resource(path="cells.lib", role="liberty", sha256=file_digest(library))},
    )
    policy = EccAdaptation(
        description_digest=document_digest(facts),
        profile_revision="reviewed-1",
        synthesis_libraries=["lib"],
        parameters={"bottom_layer": "L2"},
    )
    directory = tmp_path / "catalog"
    directory.mkdir()
    (directory / "facts.json").write_text(facts.model_dump_json())
    (directory / "policy.json").write_text(policy.model_dump_json())
    (directory / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "id": "example-r1",
                        "description_digests": [document_digest(facts)],
                        "description": "facts.json",
                        "adaptation": "policy.json",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(profiles, "PROFILE_DIRECTORY", directory)
    return root, ManagedConfiguration(description=facts, adaptation=policy), directory


def test_first_adoption_selects_exact_defaults_without_writing_pdk(bundled):
    root, expected, _ = bundled
    source = root / "ecc-pdk.json"
    source.write_text(expected.description.model_dump_json())
    before = source.read_bytes()
    path = adopt_configuration(root)
    assert read_configuration(path) == expected
    assert source.read_bytes() == before
    # User edits survive later imports/adoptions, even when the bundled default changes.
    data = expected.model_copy(deep=True)
    data.adaptation.parameters["bottom_layer"] = "USER"
    path.write_text(data.model_dump_json())
    assert read_configuration(adopt_configuration(root)) == data


def test_missing_description_requires_explicit_profile_selection(bundled):
    root, expected, _ = bundled
    with pytest.raises(DescriptorError, match="description is missing"):
        adopt_configuration(root)
    result = CliRunner().invoke(
        profiles_app, ["apply", "--root", str(root), "--profile", "example-r1"]
    )
    assert result.exit_code == 0, result.output
    assert read_configuration(configuration_path(root)) == expected
    assert not (root / "ecc-pdk.json").exists()


def test_direct_python_loading_resolves_defaults_without_replacing_explicit_snapshot(bundled):
    from chipcompiler.data.pdk import get_pdk

    root, expected, _ = bundled
    source = root / "ecc-pdk.json"
    source.write_text(expected.description.model_dump_json())
    assert get_pdk("example", root, validate=False).description == expected.resolved().model_dump()
    assert not configuration_path(root).exists()
    # An explicitly supplied snapshot is authoritative, even if it is empty policy.
    snapshot = get_pdk("example", root, pdk_config=source, validate=False)
    assert snapshot.description["parameters"] == {}


@pytest.mark.parametrize("change", ["release", "content", "corrupt"])
def test_no_name_or_version_fallback(bundled, change):
    root, expected, _ = bundled
    facts = expected.description.model_copy(deep=True)
    if change == "release":
        facts.release = "r2"
    if change == "content":
        (root / "cells.lib").write_text("changed")
    (root / "ecc-pdk.json").write_text("{" if change == "corrupt" else facts.model_dump_json())
    if change == "release":
        path = adopt_configuration(root)
        assert read_configuration(path).adaptation.synthesis_libraries == []
        with pytest.raises(DescriptorError, match="does not match"):
            profiles.apply_profile(root, "example-r1", file_digest(path))
    else:
        with pytest.raises(DescriptorError):
            adopt_configuration(root)
        assert not configuration_path(root).exists()


def test_import_without_adapter_uses_default_but_explicit_policy_wins(bundled, tmp_path):
    root, expected, _ = bundled
    source = tmp_path / "facts.json"
    source.write_text(expected.description.model_dump_json())
    path, _ = import_configuration(root, source, None)
    assert read_configuration(path) == expected
    path.unlink()
    policy = expected.adaptation.model_copy(deep=True)
    policy.parameters = {"bottom_layer": "CUSTOM"}
    file = tmp_path / "custom.json"
    file.write_text(policy.model_dump_json())
    path, _ = import_configuration(root, source, file)
    assert read_configuration(path).adaptation == policy


def test_explicit_upgrade_requires_revision_and_leaves_project_pinned(bundled, tmp_path):
    from chipcompiler.pdk.registry import register

    root, expected, directory = bundled
    path, revision = profiles.apply_profile(root, "example-r1", None)
    installation = register(root).copy()
    project = tmp_path / "project"
    project.mkdir()
    original = bind_project(project, root, expected.resolved())
    replacement = expected.adaptation.model_copy(deep=True)
    replacement.profile_revision = "reviewed-2"
    replacement.parameters["bottom_layer"] = "L3"
    (directory / "policy.json").write_text(replacement.model_dump_json())
    with pytest.raises(DescriptorError, match="supply its revision"):
        profiles.apply_profile(root, "example-r1", None)
    profiles.apply_profile(root, "example-r1", revision)
    assert load_descriptor(root).parameters == replacement.parameters
    updated = register(root)
    assert updated["pdkDigest"] == installation["pdkDigest"]
    assert updated["adaptationDigest"] != installation["adaptationDigest"]
    with pytest.raises(DescriptorError, match="configuration changed"):
        profiles.apply_profile(root, "example-r1", revision)
    assert read_lock(project / "pdk.lock.json") == original
    assert (
        load_descriptor(root, lock_workspace_inputs(project, root, "example"))
        == expected.resolved()
    )
    # A broken/new incompatible managed default must not break a locked project.
    path.write_text("{")
    cfg = ProjectConfig(project_dir=str(project), pdk_name="example", pdk_root=str(root))
    assert pdk_issues_for_config(cfg, ["Synthesis"]) == []


def test_profiles_do_not_write_when_ecc_incompatible(bundled):
    root, expected, directory = bundled
    expected.adaptation.tools = {"compatibility": {"ecc": ">=999"}}
    (directory / "policy.json").write_text(expected.adaptation.model_dump_json())
    with pytest.raises(DescriptorError, match="requires ECC"):
        profiles.apply_profile(root, "example-r1", None)
    assert not configuration_path(root).exists()


def test_registered_metadata_enrichment_fails_before_overwriting_defaults(bundled):
    from chipcompiler.pdk.registry import inventory_path, register

    root, expected, directory = bundled
    path, revision = profiles.apply_profile(root, "example-r1", None)
    register(root)
    before = path.read_bytes(), inventory_path().read_bytes()
    # The catalog explicitly accepts the old facts, but the reviewed new facts
    # would change the process identity of an already registered installation.
    enriched = expected.description.model_copy(deep=True)
    enriched.resources["second_view"] = enriched.resources["lib"]
    policy = expected.adaptation.model_copy(deep=True)
    policy.description_digest = document_digest(enriched)
    (directory / "facts.json").write_text(enriched.model_dump_json())
    (directory / "policy.json").write_text(policy.model_dump_json())
    with pytest.raises(DescriptorError, match="separate PDK root"):
        profiles.apply_profile(root, "example-r1", revision)
    assert (path.read_bytes(), inventory_path().read_bytes()) == before


def test_real_catalog_is_self_consistent_and_contains_no_absolute_resource_paths():
    from chipcompiler.pdk.tool_settings import ToolSettings

    for profile in profiles.catalog():
        configuration = profiles.profile_configuration(profile)
        assert document_digest(configuration.description) in profile.description_digests
        ToolSettings.model_validate(configuration.adaptation.tools)
        assert all(
            r.sha256 and not Path(r.path).is_absolute()
            for r in configuration.description.resources.values()
        )
        # Every selected primitive/cell role must be in the shipped semantic catalog.
        masters = {c.master for c in configuration.description.cell_catalog}
        cells = configuration.adaptation.cells
        selected = [
            cells.tap_cell,
            cells.end_cap,
            cells.tie_high_cell,
            cells.tie_low_cell,
            cells.abc_driver_cell,
            *cells.buffers,
        ]
        selected += [
            i["master"]
            for m in configuration.adaptation.tools["synthesis"]["primitive_mappings"]
            for i in m["instances"]
        ]
        assert set(selected) <= masters


def test_initial_apply_cannot_overwrite_a_concurrent_configuration(bundled, monkeypatch):
    root, expected, _ = bundled
    validate = profiles.validated_default

    def concurrent_writer(root, profile):
        checked = validate(root, profile)
        path = configuration_path(root)
        path.parent.mkdir(parents=True)
        other = expected.model_copy(deep=True)
        other.adaptation.parameters["bottom_layer"] = "CONCURRENT"
        path.write_text(other.model_dump_json())
        return checked

    monkeypatch.setattr(profiles, "validated_default", concurrent_writer)
    with pytest.raises(DescriptorError, match="already exists"):
        profiles.apply_profile(root, "example-r1", None)
    assert read_configuration(configuration_path(root)).adaptation.parameters == {
        "bottom_layer": "CONCURRENT"
    }
