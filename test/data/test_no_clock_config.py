"""Config-level no_clock: relaxes clock gates and folds CTS into skip policy."""

import pytest

from chipcompiler.cli.project.config import ProjectConfig, validate_project_config
from chipcompiler.data.workspace_config import validate_flow_config
from chipcompiler.rtl2gds import resolve_no_clock, resolve_skip_steps


def test_validate_flow_config_no_clock_materializes_cts_skip():
    section = validate_flow_config({"preset": "rtl2gds", "no_clock": True})
    assert section["no_clock"] is True
    assert "CTS" in section["skip_steps"]
    assert "lec" in section["skip_steps"]  # code default still applies


def test_validate_flow_config_rejects_cts_without_no_clock():
    from chipcompiler.data.workspace_config import WorkspaceFlowTargetError

    with pytest.raises(WorkspaceFlowTargetError, match="CTS"):
        validate_flow_config({"skip_steps": ["CTS"]})


def test_project_config_no_clock_relaxes_clock_requirements(tmp_path):
    cfg = ProjectConfig(
        design_name="combo",
        design_top="top",
        design_clock_port="",
        design_frequency_mhz=0,
        pdk_name="ics55",
        pdk_root=str(tmp_path),
        flow_preset="rtl2gds",
        flow_no_clock=True,
        project_dir=str(tmp_path),
    )
    cfg._explicit_keys = frozenset({"flow.no_clock"})
    # pdk.root must exist as a directory; contents check may still fail —
    # we only assert clock-related messages are absent.
    errors = validate_project_config(cfg)
    assert not any("clock_port" in e for e in errors)
    assert not any("frequency_mhz" in e for e in errors)
    assert cfg._no_clock_source == "explicit"


def test_project_config_empty_clock_port_infers_no_clock(tmp_path):
    cfg = ProjectConfig(
        design_name="combo",
        design_top="top",
        design_clock_port="",
        design_frequency_mhz=0,
        pdk_name="ics55",
        pdk_root=str(tmp_path),
        flow_preset="rtl2gds",
        flow_no_clock=False,
        project_dir=str(tmp_path),
    )
    errors = validate_project_config(cfg)
    assert not any("clock_port" in e for e in errors)
    assert not any("frequency_mhz" in e for e in errors)
    assert cfg._no_clock_source == "inferred"


def test_project_config_explicit_false_still_requires_clock_port(tmp_path):
    cfg = ProjectConfig(
        design_name="combo",
        design_top="top",
        design_clock_port="",
        design_frequency_mhz=0,
        pdk_name="ics55",
        pdk_root=str(tmp_path),
        flow_preset="rtl2gds",
        flow_no_clock=False,
        project_dir=str(tmp_path),
    )
    cfg._explicit_keys = frozenset({"flow.no_clock"})
    errors = validate_project_config(cfg)
    assert any("clock_port" in e for e in errors)
    assert cfg._no_clock_source == "off"


def test_resolve_skip_steps_matches_validate_flow_config():
    section = validate_flow_config({"preset": "rtl2gds", "no_clock": True, "skip_steps": []})
    assert resolve_skip_steps(section) == ("CTS",)


def test_resolve_no_clock_precedence():
    assert resolve_no_clock({"no_clock": True}, materials={"clock": "clk"}).source == "explicit"
    assert resolve_no_clock({}, materials={"clock_port": ""}).source == "inferred"
    assert resolve_no_clock({"no_clock": False}, materials={"clock_port": ""}).source == "off"
    assert resolve_no_clock({}, materials={"clock": "clk"}).source == "off"
    assert resolve_no_clock({}).source == "off"


def test_resolve_skip_steps_infers_cts_from_empty_clock_materials():
    assert "CTS" in resolve_skip_steps({}, materials={"clock_port": ""})
    assert "CTS" not in resolve_skip_steps({}, materials={"clock": "clk"})
    with pytest.raises(ValueError, match="CTS"):
        resolve_skip_steps({"skip_steps": ["CTS"]}, materials={"clock": "clk"})
