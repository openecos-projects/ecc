#!/usr/bin/env python

"""The schema-version registry: chain application, version gating, and the
legacy (version-0) load paths. The behavioral legacy migration tests live in
test_legacy_migration.py; this module covers the registry mechanics."""

import json
import tomllib
from pathlib import Path

import pytest

from chipcompiler.data.schema_migrations import (
    FLOW_JSON,
    PARAMS_TOML,
    SCHEMA_MIGRATIONS,
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
    apply_schema_migrations,
    document_schema_version,
)


def _write_flow_json(workspace_dir: Path, document: dict) -> Path:
    home = workspace_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    path = home / "flow.json"
    path.write_text(json.dumps(document))
    return path


def test_missing_field_is_version_zero():
    assert document_schema_version({}, FLOW_JSON) == 0
    assert document_schema_version({"schema_version": "1"}, FLOW_JSON) == 0
    assert document_schema_version({"schema_version": True}, FLOW_JSON) == 0
    assert document_schema_version({"schema_version": 2}, FLOW_JSON) == 2


def test_chain_applies_in_ascending_order(tmp_path, monkeypatch):
    calls: list[int] = []

    def migrate_to(target):
        def _migrate(_workspace_dir: Path) -> None:
            calls.append(target)

        return _migrate

    monkeypatch.setitem(SCHEMA_MIGRATIONS, FLOW_JSON, {2: migrate_to(2), 1: migrate_to(1)})
    monkeypatch.setitem(SUPPORTED_SCHEMA_VERSIONS, FLOW_JSON, 2)
    _write_flow_json(tmp_path, {"schema_version": 0, "steps": []})

    final = apply_schema_migrations(FLOW_JSON, tmp_path)

    assert calls == [1, 2]
    assert final == 2


def test_chain_skips_versions_at_or_below_the_file_version(tmp_path, monkeypatch):
    calls: list[int] = []

    def migrate_to(target):
        def _migrate(_workspace_dir: Path) -> None:
            calls.append(target)

        return _migrate

    monkeypatch.setitem(SCHEMA_MIGRATIONS, FLOW_JSON, {1: migrate_to(1), 2: migrate_to(2)})
    monkeypatch.setitem(SUPPORTED_SCHEMA_VERSIONS, FLOW_JSON, 2)
    _write_flow_json(tmp_path, {"schema_version": 1, "steps": []})

    final = apply_schema_migrations(FLOW_JSON, tmp_path)

    assert calls == [2]
    assert final == 2


def test_unknown_high_version_rejected_with_path_and_version(tmp_path, monkeypatch):
    monkeypatch.setitem(SCHEMA_MIGRATIONS, FLOW_JSON, {})
    path = _write_flow_json(tmp_path, {"schema_version": 9, "steps": []})

    with pytest.raises(UnsupportedSchemaVersionError) as excinfo:
        apply_schema_migrations(FLOW_JSON, tmp_path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "9" in message


def test_params_toml_migration_registered_and_stamps_version_one(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    """The 0→1 entry of the params.toml chain is the legacy parameters.json
    migration; the rewritten TOML carries schema_version = 1, so the next
    open takes no migration step."""
    from chipcompiler.data import load_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    home = workspace_dir / "home"
    home.mkdir(parents=True)
    (home / "parameters.json").write_text(
        json.dumps(
            {
                "PDK": "ics55",
                "Design": "gcd",
                "Top module": "gcd",
                "Clock": "clk",
                "Frequency max [MHz]": 250,
                "PDK Root": str(pdk_root.resolve()),
            }
        )
    )

    assert apply_schema_migrations(PARAMS_TOML, workspace_dir) == 1

    config_path = home / "params.toml"
    assert config_path.is_file()
    with open(config_path, "rb") as f:
        document = tomllib.load(f)
    assert document["schema_version"] == 1

    # The second open is version-1 already: no migration function re-runs.
    for version, fn in SCHEMA_MIGRATIONS[PARAMS_TOML].items():
        monkeypatch.setitem(
            SCHEMA_MIGRATIONS[PARAMS_TOML],
            version,
            lambda _dir, _fn=fn: pytest.fail(f"migration {_fn} re-ran for a v1 file"),
        )
    assert apply_schema_migrations(PARAMS_TOML, workspace_dir) == 1

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250


def test_load_workspace_rejects_unsupported_params_toml_version(
    tmp_path, minimal_ics55_pdk_factory
):
    from chipcompiler.data import create_workspace, load_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"

    created = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert created is not None
    config_path = workspace_dir / "home" / "params.toml"
    with open(config_path, "rb") as f:
        document = tomllib.load(f)
    document["schema_version"] = 99
    import tomli_w

    config_path.write_bytes(tomli_w.dumps(document).encode("utf-8"))

    with pytest.raises(UnsupportedSchemaVersionError) as excinfo:
        load_workspace(str(workspace_dir))

    assert str(config_path) in str(excinfo.value)
    assert "99" in str(excinfo.value)


def test_classify_workspace_rejects_unsupported_flow_json_version(tmp_path):
    from chipcompiler.engine.reconcile import classify_workspace

    home = tmp_path / "home"
    home.mkdir()
    (home / "params.toml").write_text('[design]\nname = "gcd"\n')
    flow_path = _write_flow_json(tmp_path, {"schema_version": 42, "steps": []})

    result = classify_workspace(tmp_path)

    assert result.outcome == "mismatch"
    assert result.error is not None
    assert result.error.startswith("unsupported_schema_version")
    assert str(flow_path) in result.error
    assert "42" in result.error


def test_new_flow_json_carries_schema_version(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    from chipcompiler.data import create_workspace

    created = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
        flow_config={"start_step": "Place", "end_step": "Route"},
    )
    assert created is not None

    flow_data = json.loads((workspace_dir / "home" / "flow.json").read_text())
    assert flow_data["schema_version"] == 1

    # The versioned ledger still loads: a leading version-0 file is legal.
    flow_path = workspace_dir / "home" / "flow.json"
    legacy = dict(flow_data)
    del legacy["schema_version"]
    flow_path.write_text(json.dumps(legacy))
    from chipcompiler.engine.reconcile import classify_workspace

    assert classify_workspace(workspace_dir).outcome != "mismatch"
