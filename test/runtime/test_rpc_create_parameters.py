#!/usr/bin/env python

"""RPC creation path: GUI flat parameters are effective at workspace creation."""

from types import SimpleNamespace

from chipcompiler.data.parameter import load_parameter
from chipcompiler.runtime.requests import WorkspaceCreateRequest
from chipcompiler.runtime.workspace_api import WorkspaceRuntimeApi


def _make_api(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.runtime.workspace_api.build_flow_for_workspace",
        lambda _workspace: SimpleNamespace(),
    )
    return WorkspaceRuntimeApi()


def _create(api, workspace_dir, pdk_root, parameters):
    tech = pdk_root / "tech.lef"
    lef = pdk_root / "stdcell.lef"
    liberty = pdk_root / "stdcell.lib"
    for path in (tech, lef, liberty):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VERSION 5.8 ;\n")

    return api.create_workspace(
        WorkspaceCreateRequest(
            directory=str(workspace_dir),
            pdk="ics55",
            pdk_json={
                "name": "ics55",
                "root": str(pdk_root),
                "tech": str(tech),
                "lefs": [str(lef)],
                "libs": [str(liberty)],
            },
            parameters=parameters,
        )
    )


def test_gui_flat_parameters_are_effective_at_creation(monkeypatch, tmp_path):
    api = _make_api(monkeypatch)
    workspace_dir = tmp_path / "workspace"

    _create(
        api,
        workspace_dir,
        tmp_path / "pdk",
        {"frequency_max": 200, "top_module": "gcd", "design": "gcd", "clock": "clk"},
    )

    persisted = load_parameter(workspace_dir / "home" / "params.toml").data
    assert persisted["frequency_max"] == 200
    assert persisted["top_module"] == "gcd"
    assert persisted["design"] == "gcd"
    assert persisted["clock"] == "clk"


def test_gui_geometry_aliases_fold_into_subtrees(monkeypatch, tmp_path):
    api = _make_api(monkeypatch)
    workspace_dir = tmp_path / "workspace"

    _create(
        api,
        workspace_dir,
        tmp_path / "pdk",
        {
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "die_width": 150,
            "die_height": 160,
            "utilitization": 0.5,
            "margin": 3,
            "die_area_mode": "width_height",
        },
    )

    persisted = load_parameter(workspace_dir / "home" / "params.toml").data
    assert persisted["die"]["size"] == [150, 160]
    assert persisted["core"]["utilitization"] == 0.5
    assert persisted["core"]["margin"] == [3, 3]
    # The GUI-only mode key never lands in the persisted configuration.
    assert "die_area_mode" not in persisted
    assert "die_width" not in persisted


def test_legacy_long_keys_in_rpc_payload_are_normalized(monkeypatch, tmp_path):
    api = _make_api(monkeypatch)
    workspace_dir = tmp_path / "workspace"

    _create(
        api,
        workspace_dir,
        tmp_path / "pdk",
        {"Design": "gcd", "Top module": "gcd", "Clock": "clk", "Frequency max [MHz]": 300},
    )

    persisted = load_parameter(workspace_dir / "home" / "params.toml").data
    assert persisted["frequency_max"] == 300
    assert "Frequency max [MHz]" not in persisted


def test_gui_geometry_reaches_floorplan_config(monkeypatch, tmp_path):
    import json

    api = _make_api(monkeypatch)
    workspace_dir = tmp_path / "workspace"

    _create(
        api,
        workspace_dir,
        tmp_path / "pdk",
        {
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "die_width": 150,
            "die_height": 160,
            "utilitization": 0.5,
            "margin": 3,
            "die_area_mode": "width_height",
        },
    )

    floorplan = json.loads((workspace_dir / "config" / "floorplan_ecc.json").read_text())
    die_builder = floorplan["die_builder"]
    assert die_builder["mode"] == "die_size"
    assert die_builder["die_size"]["width_micron"] == 150
    assert die_builder["die_size"]["height_micron"] == 160
    assert die_builder["margin"]["left_micron"] == 3
    assert die_builder["margin"]["top_micron"] == 3
    assert die_builder["die_util"]["utilization"] == 0.5
