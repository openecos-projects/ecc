import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import EccOutput, EccStep, StateEnum, StepEnum, Workspace

from ._sizer_helpers import _sizer_runtime, _subflow_states, _workspace


class ExplodingEccModule:
    def __getattribute__(self, name):
        raise AssertionError(f"Sizer runner used ecc_module.{name}")


class FakeLegalizeModule:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _write_staging(step: EccStep) -> None:
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    staging_def = sizer_builder.sizer_staging_def(step)
    staging_verilog = sizer_builder.sizer_staging_verilog(step)
    staging_def.parent.mkdir(parents=True, exist_ok=True)
    staging_def.write_text("def\n", encoding="utf-8")
    staging_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")


def _fake_sizer_run(step: EccStep):
    def fake_run(command, cwd, stdout, stderr, check):
        del command, cwd, stdout, stderr, check
        _write_staging(step)
        return SimpleNamespace(returncode=0)

    return fake_run


def _patch_success_legalize(monkeypatch, sizer_runner, step: EccStep, ecc=None):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    legalize_module = ecc or FakeLegalizeModule()
    seen = []

    def fake_legalize(workspace, owner_step, input_def, input_verilog):
        del workspace
        seen.append((owner_step, Path(input_def), Path(input_verilog)))
        assert owner_step is step
        assert Path(input_def) == sizer_builder.sizer_staging_def(step)
        assert Path(input_verilog) == sizer_builder.sizer_staging_verilog(step)
        return legalize_module

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        os.makedirs(os.path.dirname(str(step.output.def_)), exist_ok=True)
        Path(step.output.def_).write_text("legal def\n", encoding="utf-8")
        Path(step.output.verilog).write_text("module gcd; endmodule\n", encoding="utf-8")
        if step.output.geometry_manifest is not None:
            Path(step.output.geometry).mkdir(parents=True, exist_ok=True)
            Path(step.output.geometry_manifest).write_text("schema=ecc.geometry.v1\n")
        return True

    monkeypatch.setattr(sizer_runner, "legalize_layout", fake_legalize)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)
    legalize_module.seen = seen
    return legalize_module


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


def test_sizer_success_legalize_failure_leaves_published_outputs_empty(tmp_path, monkeypatch):
    from chipcompiler.engine.flow import EngineFlow
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
    Path(step.output.def_).parent.mkdir(parents=True, exist_ok=True)
    Path(step.output.def_).write_text("stale\n", encoding="utf-8")
    Path(step.output.verilog).write_text("stale\n", encoding="utf-8")

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))
    monkeypatch.setattr(sizer_runner, "legalize_layout", lambda *args, **kwargs: None)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    states = _subflow_states(step)
    assert states["run sizer"] == StateEnum.Success.value
    assert states["run legalization"] == StateEnum.Imcomplete.value
    assert not Path(step.output.def_).exists()
    assert not Path(step.output.verilog).exists()
    assert sizer_builder.sizer_staging_def(step).is_file()
    assert EngineFlow(Workspace()).check_step_result(step) is False


def test_sizer_save_data_failure_deletes_partial_outputs(tmp_path, monkeypatch):
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

    legalize_module = FakeLegalizeModule()

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        Path(step.output.def_).parent.mkdir(parents=True, exist_ok=True)
        Path(step.output.def_).write_text("partial\n", encoding="utf-8")
        return False

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))
    monkeypatch.setattr(sizer_runner, "legalize_layout", lambda *args, **kwargs: legalize_module)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    assert _subflow_states(step)["save data"] == StateEnum.Imcomplete.value
    assert not Path(step.output.def_).exists()
    assert legalize_module.closed is True


def test_sizer_save_data_failure_deletes_feature_report_and_image(tmp_path, monkeypatch):
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
    Path(step.feature.db).write_text("stale feature\n", encoding="utf-8")
    Path(step.report.db).write_text("stale report\n", encoding="utf-8")
    Path(step.output.image).write_text("stale image\n", encoding="utf-8")

    legalize_module = FakeLegalizeModule()

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        Path(step.feature.db).write_text("partial feature\n", encoding="utf-8")
        return False

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))
    monkeypatch.setattr(sizer_runner, "legalize_layout", lambda *args, **kwargs: legalize_module)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    assert not Path(step.feature.db).exists()
    assert not Path(step.report.db).exists()
    assert not Path(step.output.image).exists()
    assert legalize_module.closed is True


def test_sizer_closes_engine_when_published_cleanup_fails(tmp_path, monkeypatch):
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

    legalize_module = FakeLegalizeModule()

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        Path(step.output.def_).parent.mkdir(parents=True, exist_ok=True)
        Path(step.output.def_).write_text("partial\n", encoding="utf-8")
        return False

    delete_calls = []

    def exploding_delete(step):
        delete_calls.append(step)
        if len(delete_calls) > 1:
            raise OSError("cannot unlink")

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))
    monkeypatch.setattr(sizer_runner, "legalize_layout", lambda *args, **kwargs: legalize_module)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)
    monkeypatch.setattr(sizer_runner, "_delete_published_outputs", exploding_delete)

    with pytest.raises(OSError, match="cannot unlink"):
        sizer_runner.run_step(workspace, step)
    assert legalize_module.closed is True


def test_sizer_rerun_does_not_legalize_stale_staging_when_sizer_writes_nothing(
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
    _write_staging(step)
    sizer_builder.sizer_staging_def(step).write_text("stale def\n", encoding="utf-8")

    legalize_calls = []

    def fake_legalize(*args, **kwargs):
        legalize_calls.append((args, kwargs))
        return FakeLegalizeModule()

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, cwd, stdout, stderr, check: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(sizer_runner, "legalize_layout", fake_legalize)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    assert legalize_calls == []
    assert not sizer_builder.sizer_staging_def(step).exists()
    assert not sizer_builder.sizer_staging_verilog(step).exists()


def test_sizer_save_data_exception_deletes_partial_outputs(tmp_path, monkeypatch):
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

    legalize_module = FakeLegalizeModule()

    def fake_save(*, workspace, step, ecc_module, feature_step):
        del workspace, ecc_module, feature_step
        Path(step.output.def_).parent.mkdir(parents=True, exist_ok=True)
        Path(step.output.def_).write_text("partial\n", encoding="utf-8")
        raise RuntimeError("geometry snapshot failed")

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))
    monkeypatch.setattr(sizer_runner, "legalize_layout", lambda *args, **kwargs: legalize_module)
    monkeypatch.setattr(sizer_runner.ecc_runner, "save_data", fake_save)

    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    assert _subflow_states(step)["save data"] == StateEnum.Imcomplete.value
    assert not Path(step.output.def_).exists()
    assert legalize_module.closed is True


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


def test_timing_opt_step_result_requires_declared_geometry_manifest(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    output_def = tmp_path / "out.def"
    output_verilog = tmp_path / "out.v"
    geometry = tmp_path / "geometry"
    output_def.write_text("def\n", encoding="utf-8")
    output_verilog.write_text("module gcd; endmodule\n", encoding="utf-8")

    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        tool="sizer",
        output=EccOutput(
            def_=output_def,
            verilog=output_verilog,
            geometry=geometry,
            geometry_manifest=geometry / "geometry.manifest",
        ),
    )

    assert EngineFlow(Workspace()).check_step_result(step) is False
    geometry.mkdir()
    (geometry / "geometry.manifest").write_text("schema=ecc.geometry.v1\n")
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_engine_flow_clears_cached_db_after_successful_sizer_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools_api
    from chipcompiler.engine import flow as flow_module
    from chipcompiler.engine.flow import EngineFlow

    workspace = _workspace(tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    # Preferred order is legalization then Timing Opt; a trailing extra
    # legalize sibling after Timing Opt is still a valid cached-DB boundary.
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


def test_engine_flow_clears_cached_db_after_incomplete_sizer_step(tmp_path, monkeypatch):
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
            }
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
    closed = []

    class CloseableDb:
        engine = "pre-sizer-db"

        def has_init(self):
            return True

        def close(self):
            closed.append(True)

    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [sizer_step]
    monkeypatch.setattr(engine_flow, "engine_db", CloseableDb())
    monkeypatch.setattr(engine_flow, "init_db_engine", lambda: True)
    monkeypatch.setattr(tools_api, "run_step", lambda **kwargs: StateEnum.Imcomplete)
    monkeypatch.setattr(tools_api, "save_layout_image", lambda workspace, step: True)
    monkeypatch.setattr(flow_module, "log_flow", lambda workspace: None)

    assert engine_flow.run_steps() is False
    assert closed == [True]
    assert engine_flow.engine_db is None
