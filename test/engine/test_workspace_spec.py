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
        "throughStepId": "lec",
    }
    spec["parameters"] = {"design.frequency_mhz": 200.0}
    workspace = create_workspace_from_spec(tmp_path / "workspace", spec, bindings)

    assert [step["name"] for step in load_workspace(workspace.directory).flow.steps()] == [
        "Synthesis",
        "lec",
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
    after = read_engineering_snapshot(updated)
    repeated = update_workspace_from_spec(
        target,
        before["workspaceRevision"],
        updated_spec,
        bindings,
        "update-1",
    )

    assert after["workspaceId"] == before["workspaceId"]
    assert after["workspaceRevision"] == before["workspaceRevision"] + 1
    assert read_engineering_snapshot(repeated) == after
    assert repeated.parameters.data["frequency_max"] == 250.0

    with pytest.raises(WorkspaceLifecycleError) as conflict:
        update_workspace_from_spec(
            target,
            before["workspaceRevision"],
            payload["workspaceSpec"],
            bindings,
            "update-2",
        )
    assert conflict.value.code == "revision_conflict"
    assert read_engineering_snapshot(repeated) == after
