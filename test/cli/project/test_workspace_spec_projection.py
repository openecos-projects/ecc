from types import SimpleNamespace

from chipcompiler.cli.project.workspace_spec import workspace_update_spec


def _config(tmp_path):
    return SimpleNamespace(
        design_name="gcd",
        design_top="gcd",
        design_clock_port="clk",
        design_rtl=["rtl/gcd.v"],
        design_netlist="netlist/gcd.v",
        design_golden_netlist="",
        design_def="layout/gcd.def",
        design_sdc="",
        design_spef="",
        flow_preset="rtl2gds",
        pdk_name="ics55",
        pdk_root=str(tmp_path / "pdk"),
        project_dir=str(tmp_path),
    )


def _snapshot(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.project.workspace_spec.read_engineering_snapshot_from_directory",
        lambda _path: {
            "workspaceSpec": {"parameters": {"place.target_density": 0.7}},
            "workspaceBindings": {},
        },
    )


def test_refresh_projection_uses_rtl_for_synthesis_entry(tmp_path, monkeypatch):
    _snapshot(monkeypatch)

    spec, bindings = workspace_update_spec("workspace", _config(tmp_path), None)

    assert spec["inputMode"] == "rtl"
    assert [item["role"] for item in spec["inputs"]] == ["rtl", "def"]
    assert "netlist" not in bindings["inputs"]


def test_refresh_projection_uses_netlist_for_physical_entry(tmp_path, monkeypatch):
    _snapshot(monkeypatch)

    spec, bindings = workspace_update_spec(
        "workspace",
        _config(tmp_path),
        {"start_step": "place", "end_step": "route"},
    )

    assert spec["inputMode"] == "postSynthesis"
    assert [item["role"] for item in spec["inputs"]] == ["netlist", "def"]
    assert "rtl-0" not in bindings["inputs"]
