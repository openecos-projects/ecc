import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import EccOutput, EccStep, StateEnum, StepEnum, Workspace

from ._sizer_helpers import _sizer_runtime, _subflow_states, _workspace


def test_sizer_runner_invokes_generated_command_and_checks_outputs(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder
    from chipcompiler.tools.ecc_sizer import runner as sizer_runner

    class ExplodingEccModule:
        def __getattribute__(self, name):
            raise AssertionError(f"Sizer runner used ecc_module.{name}")

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
        os.makedirs(os.path.dirname(str(step.output.def_)), exist_ok=True)
        with open(str(step.output.def_), "w", encoding="utf-8") as file:
            file.write("def\n")
        with open(str(step.output.verilog), "w", encoding="utf-8") as file:
            file.write("module gcd; endmodule\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert (
        sizer_runner.run_step(
            workspace,
            step,
            ecc_module=ExplodingEccModule(),
        )
        == StateEnum.Success
    )
    assert _subflow_states(step)["run sizer"] == StateEnum.Success.value
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
    assert step.script.sizer_cmd is not None
    os.remove(step.script.sizer_cmd)

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
        input_def=Path("input.def"),
        input_verilog=Path("input.v"),
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


def test_timing_opt_step_result_does_not_require_gds(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    output_def = tmp_path / "out.def"
    output_verilog = tmp_path / "out.v"
    output_def.write_text("def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")

    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=output_def,
            verilog=output_verilog,
            gds=tmp_path / "missing.gds",
        ),
    )

    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_engine_flow_clears_cached_db_after_successful_sizer_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools_api
    from chipcompiler.engine import flow as flow_module
    from chipcompiler.engine.flow import EngineFlow

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
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

    sizer_step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=tmp_path / "sizer.def",
            verilog=tmp_path / "sizer.v",
        ),
    )
    post_sizer_step = EccStep(
        name=StepEnum.LEGALIZATION.value,
        tool="ecc",
        output=EccOutput(
            def_=tmp_path / "post.def",
            verilog=tmp_path / "post.v",
            gds=tmp_path / "post.gds",
        ),
    )
    pre_sizer_db_closed = []

    class CloseableDb:
        engine = "pre-sizer-db"

        def has_init(self):
            return True

        def close(self):
            pre_sizer_db_closed.append(True)

    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [sizer_step, post_sizer_step]
    monkeypatch.setattr(engine_flow, "engine_db", CloseableDb())

    init_seen = []
    run_seen = []

    def fake_init_db_engine():
        current_db = engine_flow.engine_db
        init_seen.append(None if current_db is None else current_db.engine)
        if current_db is None:
            assert pre_sizer_db_closed == [True]
            monkeypatch.setattr(
                engine_flow,
                "engine_db",
                SimpleNamespace(engine="post-sizer-db", has_init=lambda: True),
            )
        return True

    def fake_tool_run(workspace, step, ecc_module):
        del workspace
        run_seen.append(
            (
                step.tool,
                ecc_module,
            )
        )
        for path in (step.output.def_, step.output.verilog, step.output.gds):
            if path is None:
                continue
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
    assert pre_sizer_db_closed == [True]
    assert run_seen == [("sizer", "pre-sizer-db"), ("ecc", "post-sizer-db")]
