"""Explicit synthetic selection permits execution without claiming qualification."""

from pathlib import Path

import pytest

from chipcompiler.cli.project.run_preflight import config_issues, pdk_issues
from chipcompiler.data import PDK, EccStep, StepEnum, create_workspace
from chipcompiler.data.workspace import refresh_workspace_config
from chipcompiler.pdk.manifest import DescriptorError
from chipcompiler.tools.ecc.emir_model import SYNTHETIC_NOTICE, model_notice, resolve_model
from chipcompiler.utility import json_read


def test_explicit_synthetic_refresh_and_preflight(tmp_path, minimal_ics55_pdk_factory):
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=Path(__file__).parents[2] / "fixtures/gcd/gcd.v",
        pdk="ics55",
        pdk_root=minimal_ics55_pdk_factory(tmp_path / "pdk"),
        parameters={"config_overrides": {"emir": {"synthetic_model": "ics55"}}},
    )
    assert workspace is not None
    refresh_workspace_config(workspace)
    config = json_read(workspace.config["emir"])
    assert Path(config["technology_file_path"]).is_file()
    assert (config["model_kind"], config["qualification"]) == ("synthetic", "not_for_signoff")
    assert model_notice(workspace) == SYNTHETIC_NOTICE
    assert pdk_issues(workspace.pdk, ["emir"], emir_config=config) == []
    issues = config_issues(workspace, [EccStep(name=StepEnum.EMIR.value, tool="ecc")])
    assert len(issues) == 1
    assert issues[0]["required"] is False
    assert "NOT FOR SIGNOFF" in issues[0]["remediation"]


def test_synthetic_selection_is_explicit_and_process_specific():
    assert resolve_model(PDK(name="other"), {}).path == ""
    with pytest.raises(DescriptorError, match="ICS55"):
        resolve_model(PDK(name="other"), {"synthetic_model": "ics55"})


def test_provided_model_has_priority_over_test_fixture(tmp_path):
    path = tmp_path / "process.tech"
    path.write_text("# Provided model; qualification is not assessed here.\n")
    model = resolve_model(
        PDK(name="ics55"), {"synthetic_model": "ics55", "technology_file_path": str(path)}
    )
    assert model.path == str(path)
    assert model.synthetic is False
