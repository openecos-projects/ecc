import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.commands.pdk_configure import configure_app
from chipcompiler.pdk.configuration import write_descriptor
from chipcompiler.pdk.context import resolved_context
from chipcompiler.pdk.documents import (
    EccAdaptation,
    PdkDescription,
    document_digest,
    split_descriptor,
)
from chipcompiler.pdk.locking import bind_project, lock_workspace_inputs, read_lock, verify_lock
from chipcompiler.pdk.managed import configuration_path, read_configuration
from chipcompiler.pdk.manifest import Descriptor, Resource, load_descriptor
from chipcompiler.pdk.registry import inventory_transaction, register, relocate


def command(root, *args):
    result = CliRunner().invoke(configure_app, [args[0], "--root", str(root), *args[1:]])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_read_only_pdk_without_description_is_authored_outside_root(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir(mode=0o555)
    try:
        created = command(root, "init", "--family", "vendor")
        command(
            root,
            "set",
            "--field",
            "release",
            "--value-json",
            '"v1"',
            "--expected-revision",
            created["revision"],
        )
        assert list(root.iterdir()) == []
        stored = read_configuration(configuration_path(root))
        assert stored.description.release == "v1"
        assert load_descriptor(root) == stored.resolved()
    finally:
        root.chmod(0o755)


def test_legacy_migration_separates_policy_and_preserves_project_snapshot(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    (root / "cells.lib").write_text("library(example) {}")
    legacy = Descriptor(
        family_id="example",
        release="v1",
        resources={"lib": Resource(path="cells.lib", role="liberty")},
        synthesis_libraries=["lib"],
        tools={"configs": {"CTS": {"target_skew": 1.0}}},
    )
    source = root / "ecc-pdk.json"
    write_descriptor(source, legacy)
    original = source.read_bytes()
    project = tmp_path / "project"
    project.mkdir()
    lock = bind_project(project, root, legacy)
    command(root, "adopt")
    before = resolved_context(root, load_descriptor(root))
    shown = command(root, "show")
    command(
        root,
        "set",
        "--field",
        "tools.configs",
        "--value-json",
        '{"CTS":{"target_skew":2.0}}',
        "--expected-revision",
        shown["revision"],
    )
    after = resolved_context(root, load_descriptor(root))
    assert before["pdk_digest"] == after["pdk_digest"]
    assert before["adaptation_digest"] != after["adaptation_digest"]
    assert source.read_bytes() == original
    assert "tools" not in command(root, "export-description")
    assert command(root, "export-adaptation")["tools"]["configs"]["CTS"]["target_skew"] == 2.0
    snapshot = lock_workspace_inputs(project, root, "example")
    assert load_descriptor(root, snapshot) == legacy
    assert read_lock(project / "pdk.lock.json") == lock
    # Old lock files from before separate identities remain valid.
    old_lock = lock.model_dump(exclude={"pdk_digest", "adaptation_digest"})
    (project / "pdk.lock.json").write_text(json.dumps(old_lock))
    verify_lock(root, read_lock(project / "pdk.lock.json"))
    assert load_descriptor(root, lock_workspace_inputs(project, root, "example")) == legacy


def test_stale_migration_edit_is_rejected(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    write_descriptor(root / "ecc-pdk.json", Descriptor(family_id="example"))
    shown = command(root, "show")
    command(root, "adopt")
    result = CliRunner().invoke(
        configure_app,
        [
            "set",
            "--root",
            str(root),
            "--field",
            "release",
            "--value-json",
            '"changed"',
            "--expected-revision",
            shown["revision"],
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "revision_conflict"


def test_native_description_and_external_adaptation_use_same_contract(tmp_path):
    root = tmp_path / "vendor"
    root.mkdir()
    facts = PdkDescription(family_id="vendor", release="r2")
    source = root / "ecc-pdk.json"
    source.write_text(facts.model_dump_json())
    adapter = EccAdaptation(
        description_digest=document_digest(facts), tools={"timing": {"signoff_view": "slow"}}
    )
    profile = tmp_path / "adapter.json"
    profile.write_text(adapter.model_dump_json())
    command(root, "import", "--description", str(source), "--adaptation", str(profile))
    assert split_descriptor(load_descriptor(root)).description == facts
    assert load_descriptor(root).tools == adapter.tools
    # No family-specific implicit fallback when a description has no adaptation.
    other = tmp_path / "other"
    other.mkdir()
    (other / "ecc-pdk.json").write_text(facts.model_dump_json())
    assert load_descriptor(other).tools == {}
    wrong = adapter.model_copy(update={"description_digest": "wrong"})
    profile.write_text(wrong.model_dump_json())
    result = CliRunner().invoke(
        configure_app,
        [
            "import",
            "--root",
            str(other),
            "--description",
            str(source),
            "--adaptation",
            str(profile),
        ],
    )
    assert result.exit_code == 2
    assert not configuration_path(other).exists()


def test_inventory_allows_policy_update_and_relocation_without_vendor_description(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    shown = command(root, "init", "--family", "custom")
    record = register(root)
    command(
        root,
        "set",
        "--field",
        "parameters",
        "--value-json",
        '{"utilization":0.3}',
        "--expected-revision",
        shown["revision"],
    )
    updated = register(root)
    assert record["pdkDigest"] == updated["pdkDigest"]
    assert record["adaptationDigest"] != updated["adaptationDigest"]
    moved = tmp_path / "moved"
    root.rename(moved)
    assert relocate(record["id"], moved)["root"] == str(moved)
    assert load_descriptor(moved).parameters == {"utilization": 0.3}


@pytest.mark.parametrize("family", ["ics55", "other"])
def test_process_description_rejects_tool_policy_for_every_family(family):
    with pytest.raises(ValueError):
        PdkDescription.model_validate({"family_id": family, "tools": {"configs": {}}})


def test_old_inventory_identity_migrates_after_an_adaptation_edit(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    write_descriptor(root / "ecc-pdk.json", Descriptor(family_id="example"))
    record = register(root)
    with inventory_transaction() as inventory:
        inventory["installations"][0].pop("pdkDigest")
        inventory["installations"][0].pop("adaptationDigest")
    shown = command(root, "show")
    command(
        root,
        "set",
        "--field",
        "parameters",
        "--value-json",
        '{"max_fanout":16}',
        "--expected-revision",
        shown["revision"],
    )
    assert register(root)["pdkDigest"] == record["pdkDigest"]
