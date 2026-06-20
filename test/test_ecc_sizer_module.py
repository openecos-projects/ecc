import json
import os
import subprocess
from types import SimpleNamespace

from chipcompiler.data import (
    PDK,
    OriginDesign,
    Parameters,
    StateEnum,
    StepEnum,
    Workspace,
    WorkspaceStep,
)


def _workspace(tmp_path):
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(
            tech="tech.lef",
            lefs=["std.lef"],
            libs=["slow.lib"],
            sdc="clock.sdc",
            spef="route.spef",
        ),
        parameters=Parameters(data={"Bottom layer": "M2", "Top layer": "M7"}),
    )
    workspace.home.init(str(tmp_path / "home.json"))
    return workspace


def _subflow_states(step):
    with open(step.subflow["path"], encoding="utf-8") as file:
        subflow = json.load(file)
    return {item["name"]: item["state"] for item in subflow["steps"]}


def _sizer_runtime(tmp_path):
    root = tmp_path / "sizer-runtime"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "submit").mkdir(parents=True, exist_ok=True)
    (root / "src" / "sizer_os.tcl").write_text("# sizer tcl\n", encoding="utf-8")
    (root / "submit" / "env_base_file").write_text("-num_vt 1\n", encoding="utf-8")
    return root


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

    with open(step.script["sizer_env"], encoding="utf-8") as file:
        env_text = file.read()
    with open(step.script["sizer_cmd"], encoding="utf-8") as file:
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
        step.output["def"],
        step.data[StepEnum.TIMING_OPT.value],
    )
    expected_verilog_out = os.path.relpath(
        step.output["verilog"],
        step.data[StepEnum.TIMING_OPT.value],
    )
    assert f"-def_out_path {expected_def_out}" in cmd_text
    assert f"-verilog_out_path {expected_verilog_out}" in cmd_text
    assert "-min_route_layer M2" in cmd_text
    assert "-max_route_layer M7" in cmd_text

    with open(step.subflow["path"], encoding="utf-8") as file:
        subflow = json.load(file)
    assert [item["name"] for item in subflow["steps"]] == ["run sizer"]

    with open(step.checklist["path"], encoding="utf-8") as file:
        checklist = json.load(file)
    assert checklist["checklist"] == []


def test_sizer_step_declares_no_db_output_and_keeps_standard_dirs(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )

    assert step.output["db"] == ""
    assert step.name == StepEnum.TIMING_OPT.value
    assert step.directory.endswith("timing_optimization_sizer")
    assert not step.directory.endswith(f"{StepEnum.TIMING_OPT.value}_sizer")
    assert " " not in os.path.basename(step.output["def"])
    assert " " not in os.path.basename(step.output["verilog"])
    assert os.path.basename(step.output["def"]) == "gcd_timing_optimization.def.gz"
    assert os.path.basename(step.output["verilog"]) == "gcd_timing_optimization.v"

    sizer_builder.build_step_space(step)

    for path in (
        step.output["dir"],
        step.data["dir"],
        step.feature["dir"],
        step.report["dir"],
        step.log["dir"],
        step.script["dir"],
        step.analysis["dir"],
    ):
        assert os.path.isdir(path)
        assert "Timing optimization_sizer" not in path


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

    assert step.input["def"] == input_def
    assert step.input["verilog"] == input_verilog


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

    assert step.output["def"] == output_def
    assert step.output["verilog"] == output_verilog


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

    assert get_step_info(workspace, step, "input") == step.input
    assert get_step_info(workspace, step, "output") == step.output
    assert get_step_info(workspace, step, "subflow") == {"path": step.subflow["path"]}
    assert get_step_info(workspace, step, "checklist") == {"path": step.checklist["path"]}
    assert get_step_info(workspace, step, "config") == {
        "sizer_env": step.script["sizer_env"],
        "sizer_cmd": step.script["sizer_cmd"],
    }
    assert get_step_info(workspace, step, "unknown") == {}


def test_sizer_runner_invokes_generated_command_and_checks_outputs(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    calls = []

    def fake_run(command, cwd, stdout, stderr, check):
        calls.append((command, cwd, stderr, check))
        os.makedirs(os.path.dirname(step.output["def"]), exist_ok=True)
        with open(step.output["def"], "w", encoding="utf-8") as file:
            file.write("def\n")
        with open(step.output["verilog"], "w", encoding="utf-8") as file:
            file.write("module gcd; endmodule\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Success
    assert _subflow_states(step)["run sizer"] == StateEnum.Success.value
    assert calls == [
        (
            ["/fake/sizer", "-env", step.script["sizer_env"], "-f", step.script["sizer_cmd"]],
            step.data[StepEnum.TIMING_OPT.value],
            subprocess.STDOUT,
            False,
        )
    ]


def test_sizer_runner_marks_subflow_invalid_when_tool_or_config_missing(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: False)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value

    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    os.remove(step.script["sizer_cmd"])

    assert sizer_runner.run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value


def test_sizer_runner_marks_subflow_incomplete_when_outputs_are_missing(
    tmp_path,
    monkeypatch,
):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, cwd, stdout, stderr, check: SimpleNamespace(returncode=0),
    )

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    assert _subflow_states(step)["run sizer"] == StateEnum.Imcomplete.value


def test_public_sizer_run_marks_invalid_when_tool_missing(tmp_path, monkeypatch):
    from chipcompiler.tools import run_step as public_run_step
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)

    assert public_run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value


def test_public_sizer_run_marks_invalid_when_runtime_missing(tmp_path, monkeypatch):
    from chipcompiler.tools import run_step as public_run_step
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    monkeypatch.delenv("CHIPCOMPILER_ECC_SIZER_ROOT", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sizer = bin_dir / "Sizer"
    sizer.write_text("#!/bin/sh\n", encoding="utf-8")
    sizer.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)

    assert public_run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value
    with open(step.script["sizer_env"], encoding="utf-8") as file:
        assert "-tclFile" not in file.read()


def test_timing_opt_step_result_does_not_require_gds(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    output_def = tmp_path / "out.def"
    output_verilog = tmp_path / "out.v"
    output_def.write_text("def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")

    step = WorkspaceStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output={
            "def": str(output_def),
            "verilog": str(output_verilog),
            "gds": str(tmp_path / "missing.gds"),
        },
    )

    assert EngineFlow(workspace=None).check_step_result(step) is True


def test_engine_flow_clears_cached_db_after_successful_sizer_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools_api
    from chipcompiler.engine import flow as flow_module
    from chipcompiler.engine.flow import EngineFlow

    workspace = _workspace(tmp_path)
    workspace.flow.path = str(tmp_path / "flow.json")
    workspace.flow.data = {
        "steps": [
            {
                "name": StepEnum.TIMING_OPT.value,
                "tool": "sizer",
                "state": StateEnum.Unstart.value,
            },
            {
                "name": StepEnum.LEGALIZATION.value,
                "tool": "ecc",
                "state": StateEnum.Unstart.value,
            },
        ]
    }

    sizer_step = WorkspaceStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output={
            "def": str(tmp_path / "sizer.def"),
            "verilog": str(tmp_path / "sizer.v"),
        },
    )
    post_sizer_step = WorkspaceStep(
        name=StepEnum.LEGALIZATION.value,
        tool="ecc",
        output={
            "def": str(tmp_path / "post.def"),
            "verilog": str(tmp_path / "post.v"),
            "gds": str(tmp_path / "post.gds"),
        },
    )
    engine_flow = EngineFlow(workspace=None)
    engine_flow.workspace = workspace
    engine_flow.workspace_steps = [sizer_step, post_sizer_step]
    engine_flow.engine_db = SimpleNamespace(engine="pre-sizer-db", has_init=lambda: True)

    init_seen = []
    run_seen = []

    def fake_init_db_engine():
        init_seen.append(None if engine_flow.engine_db is None else engine_flow.engine_db.engine)
        if engine_flow.engine_db is None:
            engine_flow.engine_db = SimpleNamespace(engine="post-sizer-db", has_init=lambda: True)
        return True

    def fake_tool_run(workspace, step, ecc_module):
        del workspace
        run_seen.append(
            (
                step.tool,
                ecc_module,
            )
        )
        for path in step.output.values():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                file.write("\n")
        return StateEnum.Success

    monkeypatch.setattr(engine_flow, "init_db_engine", fake_init_db_engine)
    monkeypatch.setattr(tools_api, "run_step", fake_tool_run)
    monkeypatch.setattr(tools_api, "save_layout_image", lambda workspace, step: True)
    monkeypatch.setattr(flow_module, "log_flow", lambda workspace: None)

    assert engine_flow.run_steps() is True
    assert init_seen == ["pre-sizer-db", None]
    assert run_seen == [("sizer", "pre-sizer-db"), ("ecc", "post-sizer-db")]
