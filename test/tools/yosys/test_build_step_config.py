from pathlib import Path

import pytest

from chipcompiler.data import PDK, OriginDesign, Parameters, StepEnum, Workspace
from chipcompiler.tools.yosys import builder as yosys_builder


def _build_workspace_and_step(tmp_path, parameters=None):
    rtl_file = tmp_path / "top.v"
    rtl_file.write_text("module top; endmodule\n")

    workspace = Workspace(
        directory=str(tmp_path),
        design=OriginDesign(name="top", top_module="top", origin_verilog=str(rtl_file)),
        pdk=PDK(),
        parameters=Parameters(data={"Frequency max [MHz]": 100, **(parameters or {})}),
    )
    step = yosys_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def="",
        input_verilog=rtl_file,
    )
    yosys_builder.build_step_space(step)
    return workspace, step


def _bundled_script(name):
    scripts_dir = Path(yosys_builder.__file__).resolve().parent / "scripts"
    return (scripts_dir / name).read_text()


def test_build_step_config_copies_bundled_scripts_by_default(tmp_path):
    workspace, step = _build_workspace_and_step(tmp_path)

    yosys_builder.build_step_config(workspace, step)

    script_dir = Path(step.directory) / "script"
    assert (script_dir / "yosys_synthesis.tcl").read_text() == _bundled_script(
        "yosys_synthesis.tcl"
    )
    assert (script_dir / "init_tech.tcl").read_text() == _bundled_script("init_tech.tcl")


def test_build_step_config_applies_synthesis_script_override(tmp_path):
    custom = tmp_path / "custom_synth.tcl"
    custom.write_text("# custom synthesis\n")
    workspace, step = _build_workspace_and_step(tmp_path, {"Synthesis script": str(custom)})

    yosys_builder.build_step_config(workspace, step)

    script_dir = Path(step.directory) / "script"
    assert (script_dir / "yosys_synthesis.tcl").read_text() == "# custom synthesis\n"
    assert (script_dir / "init_tech.tcl").read_text() == _bundled_script("init_tech.tcl")


def test_build_step_config_applies_init_tech_override(tmp_path):
    custom = tmp_path / "custom_init_tech.tcl"
    custom.write_text("# custom init tech\n")
    workspace, step = _build_workspace_and_step(tmp_path, {"Init tech script": str(custom)})

    yosys_builder.build_step_config(workspace, step)

    script_dir = Path(step.directory) / "script"
    assert (script_dir / "init_tech.tcl").read_text() == "# custom init tech\n"
    assert (script_dir / "yosys_synthesis.tcl").read_text() == _bundled_script(
        "yosys_synthesis.tcl"
    )


def test_build_step_config_rejects_missing_override(tmp_path):
    workspace, step = _build_workspace_and_step(
        tmp_path, {"Synthesis script": str(tmp_path / "missing.tcl")}
    )

    with pytest.raises(ValueError, match="script override"):
        yosys_builder.build_step_config(workspace, step)


def test_build_step_config_resolves_relative_override_against_workspace(tmp_path):
    snapshot = tmp_path / "scripts" / "synth_script.tcl"
    snapshot.parent.mkdir()
    snapshot.write_text("# workspace snapshot\n")
    workspace, step = _build_workspace_and_step(
        tmp_path, {"Synthesis script": "scripts/synth_script.tcl"}
    )

    yosys_builder.build_step_config(workspace, step)

    script_dir = Path(step.directory) / "script"
    assert (script_dir / "yosys_synthesis.tcl").read_text() == "# workspace snapshot\n"


def test_build_step_config_validates_all_overrides_before_copying(tmp_path):
    custom = tmp_path / "custom_synth.tcl"
    custom.write_text("# custom synthesis\n")
    workspace, step = _build_workspace_and_step(
        tmp_path,
        {"Synthesis script": str(custom), "Init tech script": str(tmp_path / "missing.tcl")},
    )

    with pytest.raises(ValueError, match="init_tech.tcl"):
        yosys_builder.build_step_config(workspace, step)

    assert not (Path(step.directory) / "script" / "yosys_synthesis.tcl").exists()
