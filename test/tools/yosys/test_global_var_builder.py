import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from chipcompiler.data import PDK, OriginDesign, Parameters, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.yosys import builder as yosys_builder
from chipcompiler.tools.yosys.service import get_step_info
from chipcompiler.tools.yosys.subflow import YosysSubFlow


def _write_file(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _build_workspace_and_step(tmp_path, *, rtl_name="top.v", create_rtl=True, filelist=None):
    rtl_file = tmp_path / rtl_name
    if create_rtl:
        _write_file(rtl_file, "module top; endmodule\n")

    lib_a = _write_file(tmp_path / "lib" / "std cell.lib")
    lib_b = _write_file(tmp_path / "lib" / "fast.lib")
    extra_lib = _write_file(tmp_path / "lib" / "extra corner.lib")
    db_config = _write_file(
        tmp_path / "config" / "db.json",
        json.dumps({"INPUT": {"lib_path": [str(extra_lib)]}}),
    )

    workspace = Workspace(
        directory=str(tmp_path),
        design=OriginDesign(
            name="top",
            top_module="top",
            origin_verilog=str(rtl_file),
            input_filelist=str(filelist) if filelist is not None else "",
        ),
        pdk=PDK(
            libs=[str(lib_a), str(lib_b)],
            dont_use=["DFF*", "CELL WITH SPACE"],
            tie_low_cell="TIELO",
            tie_low_port="Z",
            tie_high_cell="TIEHI",
            tie_high_port="Z",
            abc_driver_cell="BUFX4",
            abc_load=0.02,
        ),
        parameters=Parameters(data={"Frequency max [MHz]": 100}),
        config={"db": str(db_config)},
    )

    step = WorkspaceStep(
        name="Synthesis",
        directory=str(tmp_path / "Synthesis_yosys"),
        input={"verilog": str(rtl_file)},
        output={"verilog": str(tmp_path / "Synthesis_yosys" / "output" / "top.v.gz")},
        data={"dir": str(tmp_path / "Synthesis_yosys" / "data")},
        feature={"stat": str(tmp_path / "Synthesis_yosys" / "feature" / "stat.json")},
        report={
            "stat": str(tmp_path / "Synthesis_yosys" / "report" / "stat.json"),
            "check": str(tmp_path / "Synthesis_yosys" / "report" / "check.rpt"),
        },
    )
    return workspace, step, rtl_file


def test_yosys_builder_constructs_path_objects_and_creates_dirs(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="top", top_module="top"),
    )
    rtl_file = tmp_path / "top.v"

    step = yosys_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def="",
        input_verilog=rtl_file,
    )

    expected_step_dir = tmp_path / f"{StepEnum.SYNTHESIS.value}_yosys"
    assert step.directory == expected_step_dir
    assert isinstance(step.directory, Path)
    assert step.input["verilog"] == rtl_file
    assert step.output["dir"] == expected_step_dir / "output"
    assert step.output["fixed_verilog"] == expected_step_dir / "output" / "top_Synthesis_fixed.v.gz"
    assert step.script["main"] == expected_step_dir / "script" / "Synthesis_main.tcl"

    yosys_builder.build_step_space(step)

    assert step.output["dir"].is_dir()
    assert step.data["tmp"].is_dir()
    assert step.script["dir"].is_dir()
    assert step.analysis["dir"].is_dir()


def test_yosys_subflow_writes_path_payload_as_json_strings(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="top", top_module="top"),
    )
    step = yosys_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def="",
        input_verilog=tmp_path / "top.v",
    )
    yosys_builder.build_step_space(step)

    YosysSubFlow(workspace, step)

    with open(step.subflow["path"], encoding="utf-8") as file:
        data = json.load(file)
    assert data["path"] == str(step.subflow["path"])


def test_yosys_step_info_stringifies_path_payloads(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="top", top_module="top"),
        config={"flow": tmp_path / "config" / "flow.json"},
    )
    step = yosys_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def="",
        input_verilog=tmp_path / "top.v",
    )

    assert get_step_info(workspace, step, "views")["image"] == str(step.output["image"])
    assert get_step_info(workspace, step, "metrics") == {"metrics": str(step.analysis["metrics"])}
    assert get_step_info(workspace, step, "subflow") == {"path": str(step.subflow["path"])}
    assert get_step_info(workspace, step, "checklist") == {"path": str(step.checklist["path"])}
    assert get_step_info(workspace, step, "config") == {"path": str(workspace.config["flow"])}


def test_plain_verilog_filelist_uses_native_parser(tmp_path):
    filelist = _write_file(tmp_path / "sources.f", "top.v\n")
    workspace, step, _ = _build_workspace_and_step(tmp_path, filelist=filelist)

    text = yosys_builder.generate_global_var_tcl(workspace, step)

    assert "set use_slang false" in text
    assert "set filelist" not in text
    assert "set rtl_file [list " in text
    assert os.path.abspath(tmp_path / "top.v") in text
    assert step.data["requires_slang"] is False


def test_systemverilog_filelist_keeps_slang_mode(tmp_path):
    source = _write_file(tmp_path / "top.sv", "module top; endmodule\n")
    filelist = _write_file(tmp_path / "sources.f", f"{source}\n")
    workspace, step, _ = _build_workspace_and_step(tmp_path, filelist=filelist)

    text = yosys_builder.generate_global_var_tcl(workspace, step)

    assert "set use_slang true" in text
    assert re.search(rf"^set\s+filelist\s+{re.escape(os.path.abspath(filelist))}$", text, re.M)
    assert "set rtl_file" not in text
    assert step.data["requires_slang"] is True


def test_rtl_mode_emits_rtl_file_as_tcl_list(tmp_path):
    workspace, step, rtl_file = _build_workspace_and_step(tmp_path)

    text = yosys_builder.generate_global_var_tcl(workspace, step)

    assert "set rtl_file [list " in text
    assert os.path.abspath(rtl_file) in text
    assert "set use_slang false" in text
    assert step.data["requires_slang"] is False


def test_lists_are_emitted_as_tcl_lists_without_split(tmp_path):
    workspace, step, _ = _build_workspace_and_step(tmp_path)

    text = yosys_builder.generate_global_var_tcl(workspace, step)

    assert "set dont_use_cells [list " in text
    assert "set lib_stdcell_list [list " in text
    assert "set lib_list [list " in text
    assert "[split" not in text
    assert "set clk_period_ps [expr {1000000.0 / $clk_freq_mhz}]" in text


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing_top", "TOP_NAME"),
        ("missing_frequency", "CLK_FREQ_MHZ"),
        ("zero_frequency", "positive number"),
        ("invalid_frequency", "positive number"),
        ("missing_inputs", "Neither RTL_FILE"),
    ],
)
def test_validation_errors_are_preserved(tmp_path, case, message):
    workspace, step, _ = _build_workspace_and_step(tmp_path)
    if case == "missing_top":
        workspace.design.top_module = ""
    elif case == "missing_frequency":
        workspace.parameters.data.pop("Frequency max [MHz]")
    elif case == "zero_frequency":
        workspace.parameters.data["Frequency max [MHz]"] = 0
    elif case == "invalid_frequency":
        workspace.parameters.data["Frequency max [MHz]"] = "fast"
    elif case == "missing_inputs":
        step.input["verilog"] = str(tmp_path / "missing.v")

    with pytest.raises(ValueError, match=message):
        yosys_builder.generate_global_var_tcl(workspace, step)


def test_paths_with_spaces_remain_single_tcl_list_element(tmp_path):
    if shutil.which("tclsh") is None:
        pytest.skip("tclsh is not available")

    workspace, step, rtl_file = _build_workspace_and_step(
        tmp_path,
        rtl_name="rtl input.v",
    )

    text = yosys_builder.generate_global_var_tcl(workspace, step)
    result = subprocess.run(
        ["tclsh"],
        input=text + "\nputs [llength $rtl_file]\nputs [lindex $rtl_file 0]\n",
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines()[-2:] == ["1", os.path.abspath(rtl_file)]


def test_liberty_args_keep_paths_with_spaces_as_single_arguments(tmp_path):
    if shutil.which("tclsh") is None:
        pytest.skip("tclsh is not available")

    workspace, step, _ = _build_workspace_and_step(tmp_path)
    init_tech = (
        Path(yosys_builder.__file__).resolve().parent / "scripts" / "init_tech.tcl"
    )

    text = yosys_builder.generate_global_var_tcl(workspace, step)
    result = subprocess.run(
        ["tclsh"],
        input=(
            text
            + "\nproc yosys args {}\n"
            + f"source {{{init_tech}}}\n"
            + "foreach arg $liberty_args {puts \"LIB:$arg\"}\n"
            + "foreach arg $tech_cells_args {puts \"STD:$arg\"}\n"
        ),
        text=True,
        capture_output=True,
        check=True,
    )

    lib_args = [
        line.removeprefix("LIB:") for line in result.stdout.splitlines() if line.startswith("LIB:")
    ]
    stdcell_args = [
        line.removeprefix("STD:") for line in result.stdout.splitlines() if line.startswith("STD:")
    ]

    assert lib_args == [
        "-liberty",
        os.path.abspath(tmp_path / "lib" / "std cell.lib"),
        "-liberty",
        os.path.abspath(tmp_path / "lib" / "fast.lib"),
        "-liberty",
        os.path.abspath(tmp_path / "lib" / "extra corner.lib"),
    ]
    assert stdcell_args == [
        "-liberty",
        os.path.abspath(tmp_path / "lib" / "std cell.lib"),
        "-liberty",
        os.path.abspath(tmp_path / "lib" / "fast.lib"),
    ]
