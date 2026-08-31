import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StateEnum, StepEnum

from ._sizer_helpers import (
    ExplodingEccModule,
    _patch_success_legalize,
    _sizer_runtime,
    _subflow_states,
    _workspace,
    _write_staging,
)


def test_sizer_runner_invokes_generated_command_and_checks_outputs(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    calls = []

    def fake_run(command, cwd, stdout, stderr, check):
        calls.append((command, cwd, stderr, check))
        _write_staging(step)
        return SimpleNamespace(returncode=0)

    legalize_module = _patch_success_legalize(monkeypatch, sizer_runner, step)
    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert (
        sizer_runner.run_step(
            workspace,
            step,
            ecc_module=ExplodingEccModule(),
        )
        == StateEnum.Success
    )
    states = _subflow_states(step)
    assert states["run sizer"] == StateEnum.Success.value
    assert states["run legalization"] == StateEnum.Success.value
    assert states["save data"] == StateEnum.Success.value
    assert Path(step.output.def_).read_text(encoding="utf-8") == "legal def\n"
    assert not Path(step.output.def_).read_text(encoding="utf-8").startswith("def\n")
    assert legalize_module.closed is True
    assert len(legalize_module.seen) == 1
    assert calls == [
        (
            [
                "/fake/sizer",
                "-env",
                str(step.script.sizer_env),
                "-f",
                str(step.script.sizer_cmd),
            ],
            str(step.data.steps[StepEnum.TIMING_OPT.value]),
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
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: False)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value

    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    assert step.script.sizer_cmd is not None
    os.remove(step.script.sizer_cmd)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value


def test_sizer_runner_does_not_run_sizer_when_dreamplace_is_missing(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    workspace = _workspace(tmp_path)
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.TIMING_OPT.value,
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    ran = []
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: ran.append((args, kwargs)) or SimpleNamespace(returncode=0),
    )

    assert sizer_runner.run_step(workspace, step) == StateEnum.Invalid
    assert ran == []
    assert _subflow_states(step)["run legalization"] == StateEnum.Invalid.value
    assert not Path(step.output.def_).exists()


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
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)
    sizer_builder.build_step_config(workspace, step)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
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
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
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
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
    )
    sizer_builder.build_step_space(step)

    assert public_run_step(workspace, step) == StateEnum.Invalid
    assert _subflow_states(step)["run sizer"] == StateEnum.Invalid.value
    with open(str(step.script.sizer_env), encoding="utf-8") as file:
        assert "-tclFile" not in file.read()
