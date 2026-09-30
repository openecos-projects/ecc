import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.engine.workspace_spec import (
    describe_workspace_spec,
    validate_workspace_spec,
)


def _valid_spec():
    return {
        "schemaVersion": 1,
        "design": {"name": "gcd", "topModule": "gcd", "clockPort": "clk"},
        "inputMode": "rtl",
        "inputs": [{"inputId": "rtl-main", "role": "rtl"}],
        "pdk": {"familyId": "ics55", "mode": "default"},
        "flow": {"flowId": "rtl2gds"},
        "parameters": {"design.frequency_mhz": 200.0},
    }


def _shared_fixture(name: str):
    root = Path(__file__).parents[1] / "fixtures" / "workspace_spec"
    payload = json.loads((root / name).read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {key: str(root / value) for key, value in bindings["inputs"].items()}
    bindings["pdk"]["root"] = str(root / bindings["pdk"]["root"])
    return payload, bindings


def test_shared_workspace_spec_fixtures_cover_valid_and_invalid_contracts():
    valid, valid_bindings = _shared_fixture("valid.json")
    assert validate_workspace_spec(valid["workspaceSpec"], valid_bindings)["issues"] == []

    invalid, invalid_bindings = _shared_fixture("invalid.json")
    result = validate_workspace_spec(invalid["workspaceSpec"], invalid_bindings)
    assert {issue["code"] for issue in result["issues"]} >= set(invalid["expectedIssueCodes"])


def test_workspace_spec_discovery_and_validation_are_canonical_and_side_effect_free(tmp_path):
    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd(input clk); endmodule\n")
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    discovery = describe_workspace_spec()
    result = validate_workspace_spec(
        _valid_spec(),
        {"inputs": {"rtl-main": str(rtl)}, "pdk": {"root": str(pdk)}},
    )

    assert discovery["schemaVersion"] == 1
    assert {item["id"] for item in discovery["parameterCatalog"]} >= {
        "design.frequency_mhz",
        "floorplan.core_util",
    }
    flows = {flow["flowId"]: flow for flow in discovery["flowDefinitions"]}
    rtl2gds = flows["rtl2gds"]
    assert set(rtl2gds["skippableStepIds"]) == {"lec", "postRouteLec", "Timing optimization"}
    assert set(rtl2gds["skippableStepIds"]) <= set(rtl2gds["stepIds"])
    assert rtl2gds["defaultSkippedStepIds"] == ["lec"]
    assert result["issues"] == []
    assert result["resolvedWorkspaceSpec"]["parameters"]["design.frequency_mhz"] == 200.0
    assert result["resolvedWorkspaceSpec"]["parameters"]["floorplan.core_util"] == 0.4
    assert len(result["resolvedWorkspaceSpec"]["pdk"]["contentHash"]) == 64
    assert str(pdk) not in json.dumps(result["resolvedWorkspaceSpec"])
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before


def test_workspace_spec_reports_structured_binding_and_input_cardinality_issues(tmp_path):
    filelist = tmp_path / "sources.f"
    filelist.write_text("missing.v\n")
    spec = _valid_spec()
    spec["inputs"] = [
        {"inputId": "rtl-main", "role": "rtl"},
        {"inputId": "sources", "role": "filelist"},
    ]

    result = validate_workspace_spec(
        spec,
        {
            "inputs": {"sources": str(filelist), "unknown": str(filelist)},
            "pdk": {"root": str(tmp_path)},
        },
    )

    assert {(issue["code"], issue["path"]) for issue in result["issues"]} >= {
        ("conflicting_input_roles", "/inputs"),
        ("input_binding_missing", "/bindings/inputs/rtl-main"),
        ("unknown_input_binding", "/bindings/inputs/unknown"),
        ("filelist_source_missing", "/bindings/inputs/sources"),
    }
    assert "resolvedWorkspaceSpec" not in result


def test_workspace_spec_rejects_multiple_manual_pdk_technology_files(tmp_path):
    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd; endmodule\n")
    for name in ("a.tech.lef", "b.tech.lef", "cells.lef", "typ.lib"):
        (tmp_path / name).write_text(name)
    spec = _valid_spec()
    spec["pdk"] = {
        "familyId": "ics55",
        "mode": "manual",
        "files": [
            {"fileId": "tech-a", "role": "tech"},
            {"fileId": "tech-b", "role": "tech"},
            {"fileId": "cells", "role": "lef"},
            {"fileId": "lib", "role": "liberty"},
        ],
    }

    result = validate_workspace_spec(
        json.loads(json.dumps(spec)),
        {
            "inputs": {"rtl-main": str(rtl)},
            "pdk": {
                "root": str(tmp_path),
                "files": {
                    "tech-a": str(tmp_path / "a.tech.lef"),
                    "tech-b": str(tmp_path / "b.tech.lef"),
                    "cells": str(tmp_path / "cells.lef"),
                    "lib": str(tmp_path / "typ.lib"),
                },
            },
        },
    )

    assert any(issue["code"] == "pdk_tech_cardinality" for issue in result["issues"])


def test_validated_workspace_spec_creates_main_compatible_workspace(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import create_workspace_from_spec

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"

    created = create_workspace_from_spec(
        target,
        payload["workspaceSpec"],
        bindings,
        "create-1",
    )
    reopened = load_workspace(target)

    assert created.directory == target
    assert reopened.directory == target
    assert reopened.design.name == "gcd"
    assert reopened.parameters.data["frequency_max"] == 200.0
    assert reopened.flow.steps()[0]["name"] == "Synthesis"
    cts = json.loads(reopened.config["CTS"].read_text(encoding="utf-8"))
    assert cts["buffer_type"] == reopened.pdk.buffers
    assert "config_overrides" not in reopened.parameters.data


def test_workspace_spec_applies_config_target_parameters(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import create_workspace_from_spec

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    spec = deepcopy(payload["workspaceSpec"])
    spec["parameters"]["cts.skew_bound"] = "0.12"

    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)
    reopened = load_workspace(workspace.directory)
    cts = json.loads(reopened.config["CTS"].read_text(encoding="utf-8"))

    assert cts["skew_bound"] == "0.12"
    assert reopened.parameters.data["config_overrides"] == {"CTS": {"skew_bound": "0.12"}}


def test_manual_pdk_workspace_reopens_through_main_persistence(tmp_path):
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import (
        assess_execution_readiness,
        create_workspace_from_spec,
        describe_workspace_binding_requirement,
    )

    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd(input clk); endmodule\n")
    pdk_root = tmp_path / "pdk"
    pdk_root.mkdir()
    for name in ("tech.lef", "cells.lef", "typ.lib"):
        (pdk_root / name).write_text(name)
    spec = _valid_spec()
    spec["flow"] = {"flowId": "syn_sta"}
    spec["pdk"] = {
        "familyId": "ics55",
        "mode": "manual",
        "files": [
            {"fileId": "tech", "role": "tech"},
            {"fileId": "cells", "role": "lef"},
            {"fileId": "lib", "role": "liberty"},
        ],
    }
    bindings = {
        "inputs": {"rtl-main": str(rtl)},
        "pdk": {
            "root": str(pdk_root),
            "files": {
                "tech": str(pdk_root / "tech.lef"),
                "cells": str(pdk_root / "cells.lef"),
                "lib": str(pdk_root / "typ.lib"),
            },
        },
    }
    target = tmp_path / "workspace"

    create_workspace_from_spec(target, spec, bindings)
    reopened = load_workspace(target)

    assert reopened.pdk.tech == pdk_root / "tech.lef"
    assert reopened.pdk.lefs == [pdk_root / "cells.lef"]
    assert describe_workspace_binding_requirement(target)["mode"] == "manual"
    assert assess_execution_readiness(target, bindings) == {"ready": True}


def test_partial_flow_spec_preserves_requested_boundaries(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import create_workspace_from_spec

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    spec = deepcopy(payload["workspaceSpec"])
    spec["flow"] = {
        "flowId": "rtl2gds",
        "fromStepId": "Synthesis",
        "throughStepId": "preFloorplan",
    }
    spec["parameters"] = {"design.frequency_mhz": 200.0}
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)

    assert [step["name"] for step in load_workspace(workspace.directory).flow.steps()] == [
        "Synthesis",
        "preFloorplan",
    ]


def test_workspace_spec_update_is_atomic_revisioned_and_idempotent(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import (
        WorkspaceLifecycleError,
        create_workspace_from_spec,
        update_workspace_from_spec,
    )
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    before = read_engineering_snapshot(created)
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    updated = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "update-1",
    )
    after = read_engineering_snapshot(updated.workspace)
    repeated = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "update-1",
    )

    assert after["workspaceId"] == before["workspaceId"]
    assert after["workspaceRevision"] == before["workspaceRevision"] + 1
    assert read_engineering_snapshot(repeated.workspace) == after
    assert repeated.workspace.parameters.data["frequency_max"] == 250.0

    with pytest.raises(WorkspaceLifecycleError) as conflict:
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            payload["workspaceSpec"],
            bindings,
            "update-2",
        )
    assert conflict.value.code == "revision_conflict"
    assert read_engineering_snapshot(repeated.workspace) == after


def test_workspace_spec_update_preserves_omitted_config_parameters(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    initial_spec = deepcopy(payload["workspaceSpec"])
    initial_spec["parameters"]["cts.skew_bound"] = "0.12"
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, initial_spec, bindings)
    before = read_engineering_snapshot(created)

    update_spec = deepcopy(payload["workspaceSpec"])
    update_spec["parameters"] = {
        "design.frequency_mhz": 250.0,
        "cts.skew_bound": "0.20",
    }
    updated = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        update_spec,
        bindings,
        "preserve-config-1",
    )

    reopened = load_workspace(updated.workspace.directory)
    cts = json.loads(reopened.config["CTS"].read_text(encoding="utf-8"))
    assert reopened.parameters.data["frequency_max"] == 250.0
    assert cts["skew_bound"] == "0.20"


def test_workspace_spec_update_preserves_declared_sta_paths_across_pdk_migration(
    tmp_path, minimal_ics55_pdk_factory
):
    import chipcompiler.engine.workspace_configuration as workspace_configuration
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    old_pdk = minimal_ics55_pdk_factory(tmp_path / "old-pdk")
    bindings["pdk"]["root"] = str(old_pdk)
    declared_liberty = [
        {
            "corner": "MAX",
            "temperature": 25,
            "path": ["liberty/cell.lib"],
        }
    ]
    initial_spec = deepcopy(payload["workspaceSpec"])
    initial_spec["parameters"]["sta.liberty"] = declared_liberty
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, initial_spec, bindings)
    before = read_engineering_snapshot(created)
    configuration = workspace_configuration.read_workspace_configuration(created)
    assert configuration["workspaceSpec"]["parameters"]["sta.liberty"] == [
        {**declared_liberty[0], "path": [str(old_pdk / "liberty/cell.lib")]}
    ]

    new_pdk = minimal_ics55_pdk_factory(tmp_path / "new-pdk")
    update_spec = deepcopy(payload["workspaceSpec"])
    update_spec["parameters"] = {"design.frequency_mhz": 250.0}
    update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        update_spec,
        {**bindings, "pdk": {**bindings["pdk"], "root": str(new_pdk)}},
        "preserve-sta-declaration-1",
    )

    updated = load_workspace(target)
    configuration = workspace_configuration.read_workspace_configuration(updated)
    assert configuration["workspaceSpec"]["parameters"]["sta.liberty"] == [
        {**declared_liberty[0], "path": [str(new_pdk / "liberty/cell.lib")]}
    ]
    sta = json.loads(updated.config["sta"].read_text(encoding="utf-8"))
    assert sta["liberty"][0]["path"] == [str(new_pdk / "liberty/cell.lib")]


def test_workspace_spec_update_preserves_inapplicable_parameters_when_flow_changes(
    tmp_path, minimal_ics55_pdk_factory
):
    import chipcompiler.engine.workspace_configuration as workspace_configuration
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    initial_spec = deepcopy(payload["workspaceSpec"])
    initial_spec["parameters"]["cts.skew_bound"] = "0.12"
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, initial_spec, bindings)
    before = read_engineering_snapshot(created)

    update_spec = deepcopy(payload["workspaceSpec"])
    update_spec["flow"] = {"flowId": "syn_sta"}
    update_spec["parameters"] = {"design.frequency_mhz": 250.0}
    updated = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        update_spec,
        bindings,
        "preserve-config-flow-1",
    )

    configuration = workspace_configuration.read_workspace_configuration(updated.workspace)
    assert configuration["workspaceSpec"]["parameters"]["cts.skew_bound"] == "0.12"
    cts = json.loads(updated.workspace.config["CTS"].read_text(encoding="utf-8"))
    assert cts["skew_bound"] == "0.12"


def test_workspace_spec_update_preserves_unknown_config_extensions(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings)
    cts_path = target / "config" / "cts_ecc.json"
    cts = json.loads(cts_path.read_text(encoding="utf-8"))
    cts["custom_extension"] = {"enabled": True, "label": "preserve-me"}
    cts_path.write_text(json.dumps(cts), encoding="utf-8")

    update_spec = deepcopy(payload["workspaceSpec"])
    update_spec["parameters"] = {"design.frequency_mhz": 250.0}
    update_workspace_from_spec(
        target,
        read_engineering_snapshot(created)["workspaceRevision"],
        update_spec,
        bindings,
        "preserve-extension-1",
    )

    updated_cts = json.loads(cts_path.read_text(encoding="utf-8"))
    assert updated_cts["custom_extension"] == {"enabled": True, "label": "preserve-me"}


def test_workspace_spec_update_fails_when_current_config_cannot_be_read(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import WorkspaceLifecycleError, create_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings)
    before = read_engineering_snapshot(created)
    (target / "config" / "cts_ecc.json").unlink()

    from chipcompiler.engine import update_workspace_from_spec

    with pytest.raises(WorkspaceLifecycleError) as unavailable:
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            payload["workspaceSpec"],
            bindings,
            "missing-config-1",
        )

    assert unavailable.value.code == "workspace_invalid"
    assert read_engineering_snapshot(created)["workspaceRevision"] == before["workspaceRevision"]


def test_workspace_spec_update_fails_when_current_config_is_malformed(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import WorkspaceLifecycleError, create_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings)
    before = read_engineering_snapshot(created)
    (target / "config" / "cts_ecc.json").write_text("{", encoding="utf-8")

    from chipcompiler.engine import update_workspace_from_spec

    with pytest.raises(WorkspaceLifecycleError) as unavailable:
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            payload["workspaceSpec"],
            bindings,
            "malformed-config-1",
        )

    assert unavailable.value.code == "workspace_invalid"
    assert read_engineering_snapshot(created)["workspaceRevision"] == before["workspaceRevision"]


def test_workspace_spec_update_keeps_generated_filelist_relocatable(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data import load_workspace
    from chipcompiler.data.parameter import load_parameter
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings)

    second_rtl = tmp_path / "helper.v"
    second_rtl.write_text("module helper; endmodule\n", encoding="utf-8")
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["inputs"].append({"inputId": "rtl-helper", "role": "rtl"})
    updated_bindings = deepcopy(bindings)
    updated_bindings["inputs"]["rtl-helper"] = str(second_rtl)

    update_workspace_from_spec(
        target,
        read_engineering_snapshot(created)["workspaceRevision"],
        updated_spec,
        updated_bindings,
    )

    persisted = Path(load_parameter(target / "home" / "params.toml").data["file_list"])
    reopened = load_workspace(target)

    assert not persisted.is_absolute()
    assert (target / persisted).is_file()
    assert reopened.design.input_filelist == target / persisted


def test_workspace_spec_update_retain_backup_preserves_replaced_generation(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data.parameter import load_parameter
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    before = read_engineering_snapshot(created)
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    first = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "retain-update-1",
        retain_backup=True,
    )

    backup = tmp_path / ".workspace.replace-backup-1"
    assert first.backup_directory == backup
    assert backup.is_dir()
    # The new generation stands at the original path on the same lineage.
    after = read_engineering_snapshot(first.workspace)
    assert after["workspaceId"] == before["workspaceId"]
    assert after["workspaceRevision"] == before["workspaceRevision"] + 1
    assert after["cause"] == "workspace.updated"
    assert first.workspace.parameters.data["frequency_max"] == 250.0
    # The backup is the replaced generation, old snapshot and config included.
    retained = read_engineering_snapshot_from_directory(backup)
    assert retained["workspaceId"] == before["workspaceId"]
    assert retained["workspaceRevision"] == before["workspaceRevision"]
    assert retained["cause"] == "workspace.created"
    assert load_parameter(backup / "home" / "params.toml").data["frequency_max"] == 200.0

    # An idempotent retry neither recreates nor re-reports the backup.
    retry = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "retain-update-1",
        retain_backup=True,
    )
    assert retry.backup_directory is None
    assert backup.is_dir()

    # The next retaining update takes the lowest free backup number.
    second = update_workspace_from_spec(
        target,
        after["workspaceRevision"],
        updated_spec,
        bindings,
        "retain-update-2",
        retain_backup=True,
    )
    assert second.backup_directory == tmp_path / ".workspace.replace-backup-2"
    retained_second = read_engineering_snapshot_from_directory(second.backup_directory)
    assert retained_second["workspaceRevision"] == after["workspaceRevision"]


def test_workspace_spec_update_without_retain_backup_keeps_no_backup(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    result = update_workspace_from_spec(
        target,
        read_engineering_snapshot(created)["workspaceRevision"],
        updated_spec,
        bindings,
        "default-update-1",
    )

    assert result.backup_directory is None
    assert _update_sidecars(tmp_path) == []


def test_workspace_spec_update_retain_backup_failure_keeps_original_tree(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import (
        WorkspaceLifecycleError,
        create_workspace_from_spec,
        update_workspace_from_spec,
    )
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    before = read_engineering_snapshot(created)
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["inputs"].append({"inputId": "rtl-extra", "role": "rtl"})

    with pytest.raises(WorkspaceLifecycleError) as failed:
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            updated_spec,
            bindings,
            "retain-fail-1",
            retain_backup=True,
        )

    assert failed.value.code == "workspace_spec_invalid"
    assert read_engineering_snapshot(created) == before
    assert _update_sidecars(tmp_path) == []


def test_workspace_spec_update_retain_backup_rolls_back_when_reload_fails(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    import chipcompiler.engine.workspace_lifecycle as lifecycle
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import read_engineering_snapshot

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    before = read_engineering_snapshot(created)
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    original_load = lifecycle._load_committed_workspace
    loads = {"count": 0}

    def fail_post_exchange_load(path):
        if Path(path) == target:
            loads["count"] += 1
            if loads["count"] > 1:
                raise OSError("simulated post-exchange load failure")
        return original_load(path)

    monkeypatch.setattr(lifecycle, "_load_committed_workspace", fail_post_exchange_load)

    with pytest.raises(OSError, match="simulated post-exchange load failure"):
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            updated_spec,
            bindings,
            "retain-rollback-1",
            retain_backup=True,
        )

    # The rollback re-exchange restored the old tree; a failed update retains
    # no backup and leaves no staging residue.
    assert read_engineering_snapshot(created) == before
    assert _update_sidecars(tmp_path) == []


def test_workspace_spec_update_sweeps_stale_staging_siblings(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
    from chipcompiler.engine.snapshot import (
        read_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    created = create_workspace_from_spec(target, payload["workspaceSpec"], bindings, "create-1")
    before = read_engineering_snapshot(created)
    # Residue from a hard-killed earlier update: only staging siblings are
    # swept; retained backups and unrelated siblings stay untouched.
    stale = tmp_path / ".workspace.staging-crashed"
    (stale / "home").mkdir(parents=True)
    (stale / "home" / "params.toml").write_text("residue = true\n", encoding="utf-8")
    backup = tmp_path / ".workspace.replace-backup-3"
    backup.mkdir()
    unrelated = tmp_path / ".other.staging-crashed"
    unrelated.mkdir()
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "sweep-update-1",
    )

    assert not stale.exists()
    assert backup.is_dir()
    assert unrelated.is_dir()
    # No staging tree of this workspace remains (lock files are not trees).
    assert _update_sidecars(tmp_path) == [".other.staging-crashed", ".workspace.replace-backup-3"]
    after = read_engineering_snapshot_from_directory(target)
    assert after["workspaceRevision"] == before["workspaceRevision"] + 1


def _update_sidecars(directory: Path) -> list[str]:
    """Staging/backup tree siblings left behind by an in-place update."""
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_dir() and (".staging-" in path.name or ".replace-backup-" in path.name)
    )


def test_workspace_spec_stale_revision_does_not_create_missing_snapshot(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.engine import WorkspaceLifecycleError, create_workspace_from_spec

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    create_workspace_from_spec(target, payload["workspaceSpec"], bindings)
    snapshot = target / "home" / "engineering-snapshot.json"
    snapshot.unlink()

    with pytest.raises(WorkspaceLifecycleError) as conflict:
        from chipcompiler.engine import update_workspace_from_spec

        update_workspace_from_spec(
            target,
            2,
            payload["workspaceSpec"],
            bindings,
            "stale-update",
        )

    assert conflict.value.code == "revision_conflict"
    assert not snapshot.exists()


def test_workspace_spec_rejects_invalid_existing_snapshot(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.engine import (
        WorkspaceLifecycleError,
        create_workspace_from_spec,
        update_workspace_from_spec,
    )

    payload, bindings = _shared_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    target = tmp_path / "workspace"
    create_workspace_from_spec(target, payload["workspaceSpec"], bindings)
    snapshot = target / "home" / "engineering-snapshot.json"
    snapshot.write_text('{"schemaVersion": 2}', encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as invalid:
        update_workspace_from_spec(
            target,
            1,
            payload["workspaceSpec"],
            bindings,
            "invalid-snapshot-update",
        )

    assert invalid.value.code == "workspace_invalid"
    assert snapshot.read_text(encoding="utf-8") == '{"schemaVersion": 2}'
