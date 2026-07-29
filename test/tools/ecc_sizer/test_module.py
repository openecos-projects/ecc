import inspect
import json
import os
from pathlib import Path

import pytest
from rosettakit.errors import ValidationError

from chipcompiler.data import StepEnum

from ._sizer_helpers import _sizer_runtime, _workspace


def test_sizer_step_config_writes_env_and_cmd_files(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    runtime_root = _sizer_runtime(tmp_path)
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(runtime_root))

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )

    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    with open(str(step.script.sizer_env), encoding="utf-8") as file:
        env_text = file.read()
    with open(str(step.script.sizer_cmd), encoding="utf-8") as file:
        cmd_text = file.read()

    assert "-num_vt 1" in env_text
    assert f"-tclFile {runtime_root / 'src' / 'sizer_os.tcl'}" in env_text
    assert "-lef tech.lef" in env_text
    assert "-lef std.lef" in env_text
    assert "-lib slow.lib" in env_text

    assert "-top gcd" in cmd_text
    assert "-useOpenSTA" in cmd_text
    assert "-def input.def" in cmd_text
    assert "-v input.v" in cmd_text
    assert "-sdc clock.sdc" in cmd_text
    assert "-spef route.spef" in cmd_text
    assert "-asap7" not in cmd_text
    assert "-prft_only" not in cmd_text
    assert "-outputPath ." in cmd_text
    expected_def_out = os.path.relpath(
        str(step.output.def_),
        step.data.steps[StepEnum.TIMING_OPT.value],
    )
    expected_verilog_out = os.path.relpath(
        str(step.output.verilog),
        step.data.steps[StepEnum.TIMING_OPT.value],
    )
    assert f"-def_out_path {expected_def_out}" in cmd_text
    assert f"-verilog_out_path {expected_verilog_out}" in cmd_text
    assert "-min_route_layer M2" in cmd_text
    assert "-max_route_layer M7" in cmd_text

    with open(str(step.subflow.path), encoding="utf-8") as file:
        subflow = json.load(file)
    assert [item["name"] for item in subflow["steps"]] == ["run sizer"]

    with open(str(step.checklist.path), encoding="utf-8") as file:
        checklist = json.load(file)
    assert checklist["checklist"] == []


def test_sizer_config_preserves_runtime_parseable_order(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    runtime_root = _sizer_runtime(tmp_path)
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(runtime_root))

    workspace = _workspace(tmp_path)
    workspace.pdk.tech = str(tmp_path / "tech_lef" / "tech.lef")
    workspace.pdk.lefs = [tmp_path / "lef_dir" / "std_cell.lef"]
    workspace.pdk.libs = [tmp_path / "lib_dir" / "slow_corner.lib"]
    workspace.pdk.sdc = str(tmp_path / "constraints" / "main_clock.sdc")
    workspace.pdk.spef = str(tmp_path / "rcx" / "route_parasitic.spef")

    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=str(tmp_path / "inputs" / "input_def.def"),
        input_verilog=str(tmp_path / "inputs" / "input_rtl.v"),
    )

    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    with open(str(step.script.sizer_env), encoding="utf-8") as file:
        env_lines = file.read().splitlines()
    with open(str(step.script.sizer_cmd), encoding="utf-8") as file:
        cmd_lines = [line for line in file.read().splitlines() if line]

    assert env_lines[0] == "-num_vt 1"
    assert f"-lef {workspace.pdk.tech}" in env_lines
    assert f"-lef {workspace.pdk.lefs[0]}" in env_lines
    assert f"-lib {workspace.pdk.libs[0]}" in env_lines
    assert f"-tclFile {runtime_root / 'src' / 'sizer_os.tcl'}" in env_lines

    expected_def_out = os.path.relpath(
        str(step.output.def_),
        step.data.steps[StepEnum.TIMING_OPT.value],
    )
    expected_verilog_out = os.path.relpath(
        str(step.output.verilog),
        step.data.steps[StepEnum.TIMING_OPT.value],
    )
    assert cmd_lines == [
        "-useOpenSTA",
        "-top gcd",
        f"-def {step.input.def_}",
        f"-v {step.input.verilog}",
        f"-sdc {workspace.pdk.sdc}",
        f"-spef {workspace.pdk.spef}",
        "-outputPath .",
        f"-def_out_path {expected_def_out}",
        f"-verilog_out_path {expected_verilog_out}",
        "-min_route_layer M2",
        "-max_route_layer M7",
    ]


def test_sizer_cmd_omits_missing_input_paths(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=None,
        input_verilog=None,
    )

    cmd_text = sizer_builder._cmd_text(workspace, step)

    assert "-def None" not in cmd_text
    assert "-v None" not in cmd_text
    assert "-def " not in cmd_text
    assert "-v " not in cmd_text


def test_sizer_config_rejects_whitespace_paths_unsupported_by_runtime(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=str(tmp_path / "inputs" / "input def.def"),
        input_verilog="input.v",
    )

    sizer_builder.build_step_space(step)
    with pytest.raises(ValidationError, match=r"unquoted-value-needs-quoting"):
        sizer_builder.build_step_config(workspace, step)


def test_sizer_builder_uses_rosettakit_options_without_raw_workaround():
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    source = inspect.getsource(sizer_builder)

    assert "_sizer_value" not in source
    assert "_sizer_option" not in source
    assert "_sizer_options" not in source
    assert "raw_line" not in source
    assert "allow_unsafe_raw" not in source


def test_sizer_config_omits_empty_optional_paths(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))

    workspace = _workspace(tmp_path)
    workspace.pdk.sdc = ""
    workspace.pdk.spef = ""
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="",
        input_verilog="",
    )

    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    with open(str(step.script.sizer_cmd), encoding="utf-8") as file:
        cmd_lines = file.read().splitlines()

    assert "-def " not in cmd_lines
    assert "-v " not in cmd_lines
    assert "-sdc " not in cmd_lines
    assert "-spef " not in cmd_lines


def test_sizer_step_declares_no_db_output_and_keeps_standard_dirs(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )

    assert step.output.db == ""
    assert step.name == StepEnum.TIMING_OPT.value
    assert step.directory.name == "timing_optimization_sizer"
    assert not str(step.directory).endswith(f"{StepEnum.TIMING_OPT.value}_sizer")
    assert isinstance(step.directory, Path)
    assert " " not in os.path.basename(str(step.output.def_))
    assert " " not in os.path.basename(str(step.output.verilog))
    assert os.path.basename(str(step.output.def_)) == "gcd_timing_optimization.def.gz"
    assert os.path.basename(str(step.output.verilog)) == "gcd_timing_optimization.v.gz"

    sizer_builder.build_step_space(step)

    for path in (
        step.output.dir,
        step.data.dir,
        step.feature.dir,
        step.report.dir,
        step.log.dir,
        step.script.dir,
        step.analysis.dir,
    ):
        assert path and os.path.isdir(path)
        assert isinstance(path, Path)
        assert "Timing optimization_sizer" not in str(path)


def test_sizer_step_keeps_caller_input_paths(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    input_def = f"{workspace.directory}/Timing optimization_sizer_inputs/input.def"
    input_verilog = f"{workspace.directory}/Timing optimization_sizer_inputs/input.v"
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=input_def,
        input_verilog=input_verilog,
    )

    assert step.input.def_ == Path(input_def)
    assert step.input.verilog == Path(input_verilog)
    assert str(step.input.def_) == input_def
    assert str(step.input.verilog) == input_verilog


def test_sizer_step_keeps_caller_output_paths_that_share_old_prefix(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    output_def = f"{workspace.directory}/Timing optimization_sizer_outputs/output.def"
    output_verilog = f"{workspace.directory}/Timing optimization_sizer_outputs/output.v"
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
        output_def=output_def,
        output_verilog=output_verilog,
    )

    assert step.output.def_ == Path(output_def)
    assert step.output.verilog == Path(output_verilog)
    assert str(step.output.def_) == output_def
    assert str(step.output.verilog) == output_verilog


def test_sizer_command_resolves_from_path_only(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer.utility import get_sizer_command, is_eda_exist

    monkeypatch.delenv("CHIPCOMPILER_ECC_SIZER_ROOT", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sizer = bin_dir / "Sizer"
    sizer.write_text("#!/bin/sh\n", encoding="utf-8")
    sizer.chmod(0o755)

    monkeypatch.setenv("PATH", str(bin_dir))

    assert get_sizer_command() == [str(sizer)]
    assert is_eda_exist() is True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "bin")

    assert get_sizer_command() == [str(sizer)]
    assert is_eda_exist() is True

    sizer.unlink()
    sizer_lower = bin_dir / "sizer"
    sizer_lower.write_text("#!/bin/sh\n", encoding="utf-8")
    sizer_lower.chmod(0o755)

    assert get_sizer_command() == []
    assert is_eda_exist() is False

    empty_path = tmp_path / "empty"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))

    assert get_sizer_command() == []
    assert is_eda_exist() is False


def test_sizer_runtime_root_resolves_from_path_binary(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer.utility import find_sizer_root, get_sizer_root

    monkeypatch.delenv("CHIPCOMPILER_ECC_SIZER_ROOT", raising=False)
    runtime_root = _sizer_runtime(tmp_path)
    built_sizer = runtime_root / "build" / "src" / "Sizer"
    built_sizer.parent.mkdir(parents=True)
    built_sizer.write_text("#!/bin/sh\n", encoding="utf-8")
    built_sizer.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "Sizer").symlink_to(built_sizer)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert find_sizer_root() == runtime_root.resolve()
    assert get_sizer_root() == runtime_root.resolve()


def test_sizer_runtime_root_is_absent_without_env_or_discoverable_runtime(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import utility as sizer_utility

    monkeypatch.delenv("CHIPCOMPILER_ECC_SIZER_ROOT", raising=False)

    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))

    assert sizer_utility.find_sizer_root() is None
    assert sizer_utility.get_sizer_root() is None
    assert sizer_utility.is_sizer_runtime_exist() is False


def test_sizer_step_info_surfaces_include_step_local_config(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import get_step_info

    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    assert get_step_info(workspace, step, "input") == {
        "def": str(step.input.def_),
        "verilog": str(step.input.verilog),
        "db": step.input.db,
    }
    output = step.output
    assert get_step_info(workspace, step, "output") == {
        "dir": str(output.dir),
        "def": str(output.def_),
        "verilog": str(output.verilog),
        "gds": str(output.gds),
        "db": output.db,
        "image": str(output.image),
        "json": str(output.json),
        "view_json": str(output.view_json),
        "view_json_edits": str(output.view_json_edits),
        "lef": str(output.lef),
        "lib": str(output.lib),
        "spef": [str(p) for p in output.spef],
    }
    assert get_step_info(workspace, step, "subflow") == {"path": str(step.subflow.path)}
    assert get_step_info(workspace, step, "checklist") == {"path": str(step.checklist.path)}
    assert get_step_info(workspace, step, "config") == {
        "sizer_env": str(step.script.sizer_env),
        "sizer_cmd": str(step.script.sizer_cmd),
    }
    assert get_step_info(workspace, step, "unknown") == {}
