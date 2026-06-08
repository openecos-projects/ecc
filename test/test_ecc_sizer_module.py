import os
import subprocess
from types import SimpleNamespace

from chipcompiler.data import (
    OriginDesign,
    PDK,
    Parameters,
    StateEnum,
    StepEnum,
    Workspace,
    WorkspaceStep,
)


def _workspace(tmp_path):
    return Workspace(
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


def test_sizer_step_config_writes_env_and_cmd_files(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def="input.def",
        input_verilog="input.v",
    )

    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    env_text = open(step.script["sizer_env"], encoding="utf-8").read()
    cmd_text = open(step.script["sizer_cmd"], encoding="utf-8").read()

    assert "-num_vt 1" in env_text
    assert "-tclFile " in env_text
    assert "-lef tech.lef" in env_text
    assert "-lef std.lef" in env_text
    assert "-lib slow.lib" in env_text

    assert "-top gcd" in cmd_text
    assert "-def input.def" in cmd_text
    assert "-v input.v" in cmd_text
    assert "-sdc clock.sdc" in cmd_text
    assert "-spef route.spef" in cmd_text
    assert f"-outputPath {step.data[StepEnum.TIMING_OPT.value]}" in cmd_text
    assert f"-def_out_path {step.output['def']}" in cmd_text
    assert f"-verilog_out_path {step.output['verilog']}" in cmd_text
    assert "-min_route_layer M2" in cmd_text
    assert "-max_route_layer M7" in cmd_text


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
        open(step.output["def"], "w", encoding="utf-8").write("def\n")
        open(step.output["verilog"], "w", encoding="utf-8").write("module gcd; endmodule\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/Sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Success
    assert calls == [
        (
            ["/fake/Sizer", "-env", step.script["sizer_env"], "-f", step.script["sizer_cmd"]],
            step.data[StepEnum.TIMING_OPT.value],
            subprocess.STDOUT,
            False,
        )
    ]


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
