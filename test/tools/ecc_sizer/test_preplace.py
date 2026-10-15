from types import SimpleNamespace

import pytest

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc_sizer import builder, runner

from ._sizer_helpers import _sizer_runtime, _subflow_states, _workspace, _write_staging


@pytest.mark.parametrize("publish_failure", [False, True])
def test_preplace_publishes_native_pair_without_legalization(
    tmp_path, monkeypatch, publish_failure
):
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(_sizer_runtime(tmp_path)))
    workspace = _workspace(tmp_path)
    (workspace.directory / "home").mkdir(parents=True, exist_ok=True)
    step = builder.build_step(workspace, StepEnum.PREPLACE.value, "input.def", "input.v")
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)
    command = step.script.sizer_cmd.read_text()
    assert "-preplace\n" in command
    assert "-use_gr_rc 0\n" in command
    assert "-spef" not in command
    monkeypatch.setattr(runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(runner, "is_sizer_runtime_exist", lambda: True)
    monkeypatch.setattr(runner, "is_dreamplace_exist", lambda: False)

    native_calls = []
    monkeypatch.setattr(runner, "min_corner_libs", lambda _: ["fixture_ff.lib"])

    def native_run(*args, **kwargs):
        native_calls.append(args)
        _write_staging(step)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", native_run)
    if publish_failure:
        copy = runner.shutil.copy2

        def fail_verilog(source, destination):
            if destination == step.output.verilog:
                raise OSError("write failed")
            return copy(source, destination)

        monkeypatch.setattr(runner.shutil, "copy2", fail_verilog)
    state = runner.run_step(workspace, step)
    assert state is (not publish_failure)
    assert len(native_calls) == 1
    assert _subflow_states(step) == {
        "run preplace": "Success",
        "save data": "Incomplete" if publish_failure else "Success",
    }
    if publish_failure:
        assert not step.output.def_.exists() and not step.output.verilog.exists()
    else:
        assert (step.output.def_.read_text(), step.output.verilog.read_text()) == (
            "def\n",
            "module gcd; endmodule\n",
        )
