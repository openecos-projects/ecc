import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum, StepEnum, Workspace

from ._sizer_helpers import (
    FakeLegalizeModule,
    _fake_sizer_run,
    _patch_success_legalize,
    _subflow_states,
    _workspace,
    _write_staging,
)


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


def test_sizer_does_not_legalize_when_staging_cleanup_fails(tmp_path, monkeypatch):
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

    legalize_calls = []
    original_delete = sizer_runner._delete_path

    def fail_staging_delete(path):
        if Path(path).name.startswith("sizer."):
            raise OSError("cannot unlink staging")
        original_delete(path)

    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "_delete_path", fail_staging_delete)

    def record_legalize(*args, **kwargs):
        del args, kwargs
        legalize_calls.append(1)

    monkeypatch.setattr(sizer_runner, "legalize_layout", record_legalize)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, cwd, stdout, stderr, check: SimpleNamespace(returncode=0),
    )

    with pytest.raises(OSError, match="cannot unlink staging"):
        sizer_runner.run_step(workspace, step)
    assert legalize_calls == []


def test_sizer_rerun_resets_previous_subflow_success(tmp_path, monkeypatch):
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

    _patch_success_legalize(monkeypatch, sizer_runner, step)
    monkeypatch.setattr(sizer_runner, "get_sizer_command", lambda: ["/fake/sizer"])
    monkeypatch.setattr(sizer_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(sizer_runner, "is_dreamplace_exist", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_sizer_run(step))

    assert sizer_runner.run_step(workspace, step) == StateEnum.Success
    assert _subflow_states(step)["run legalization"] == StateEnum.Success.value
    assert _subflow_states(step)["save data"] == StateEnum.Success.value

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, cwd, stdout, stderr, check: SimpleNamespace(returncode=0),
    )
    assert sizer_runner.run_step(workspace, step) == StateEnum.Imcomplete
    states = _subflow_states(step)
    assert states["run sizer"] == StateEnum.Imcomplete.value
    assert states["run legalization"] == StateEnum.Unstart.value
    assert states["save data"] == StateEnum.Unstart.value


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
