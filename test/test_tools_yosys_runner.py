#!/usr/bin/env python
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StateEnum
from chipcompiler.tools.yosys import runner


def _build_workspace_and_step(tmp_path: Path):
    script_dir = tmp_path / "script"
    script_dir.mkdir()

    rtl_file = tmp_path / "top.v"
    rtl_file.write_text("module top; endmodule\n")

    output_file = tmp_path / "output.v"
    log_file = tmp_path / "yosys.log"

    workspace = SimpleNamespace(
        design=SimpleNamespace(
            input_filelist=""
        )
    )
    step = SimpleNamespace(
        input={"verilog": str(rtl_file)},
        output={"verilog": str(output_file)},
        log={"file": str(log_file)},
        script={"dir": str(script_dir)},
        directory=str(tmp_path)
    )
    return workspace, step, output_file, log_file


def test_run_step_uses_local_env_and_runs_synthesis(tmp_path, monkeypatch):
    workspace, step, output_file, _ = _build_workspace_and_step(tmp_path)
    runtime_env = {"PATH": "/opt/yosys/bin", "CUSTOM_ENV": "1"}
    updates = []
    run_calls = []
    check_calls = []

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, runtime="", memory=0, info=None):
            updates.append((step_name, state))

    class FakeChecklist:
        def __init__(self, workspace, workspace_step):
            pass

        def check(self):
            return None

    def fake_check_slang_plugin(yosys_cmd, cwd_dir, yosys_env, log_file):
        check_calls.append({
            "yosys_cmd": list(yosys_cmd),
            "cwd": cwd_dir,
            "env": yosys_env,
        })
        return True

    def fake_run(cmd, cwd, env, stdout, stderr, timeout):
        run_calls.append({
            "cmd": list(cmd),
            "cwd": cwd,
            "env": env,
            "timeout": timeout,
        })
        if cmd == ["yosys", "yosys_synthesis.tcl"]:
            output_file.write_text("module top(); endmodule\n")
            return SimpleNamespace(returncode=0)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(runner, "YosysSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "YosysChecklist", FakeChecklist)
    monkeypatch.setattr(runner, "build_step_metrics", lambda workspace, step: None)
    monkeypatch.setattr(runner, "get_yosys_runtime", lambda: (["yosys"], runtime_env))
    monkeypatch.setattr(runner, "check_slang_plugin", fake_check_slang_plugin)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_step(workspace=workspace, step=step)

    assert result is True
    assert len(check_calls) == 1
    assert check_calls[0]["yosys_cmd"] == ["yosys"]
    assert check_calls[0]["env"] == runtime_env
    assert len(run_calls) == 1
    assert run_calls[0]["cmd"] == ["yosys", "yosys_synthesis.tcl"]
    assert run_calls[0]["env"] == runtime_env
    assert ("run yosys", StateEnum.Success) in updates
    assert ("analysis", StateEnum.Success) in updates


def test_run_step_marks_invalid_when_slang_check_fails(tmp_path, monkeypatch):
    workspace, step, _, log_file = _build_workspace_and_step(tmp_path)
    updates = []
    run_calls = []

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, runtime="", memory=0, info=None):
            updates.append((step_name, state))

    def fake_check_slang_plugin(yosys_cmd, cwd_dir, yosys_env, log_file):
        log_file.write("Error: yosys slang plugin check failed.\n")
        return False

    def fake_run(cmd, cwd, env, stdout, stderr, timeout):
        run_calls.append(list(cmd))
        raise AssertionError("Synthesis should not run when slang check fails")

    monkeypatch.setattr(runner, "YosysSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "build_step_metrics", lambda workspace, step: None)
    monkeypatch.setattr(runner, "get_yosys_runtime", lambda: (["yosys"], {"PATH": "/tmp"}))
    monkeypatch.setattr(runner, "check_slang_plugin", fake_check_slang_plugin)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_step(workspace=workspace, step=step)

    assert result is False
    assert run_calls == []
    assert ("run yosys", StateEnum.Invalid) in updates
    assert "slang plugin check failed" in log_file.read_text()


def test_run_step_marks_invalid_when_yosys_is_missing(tmp_path, monkeypatch):
    workspace, step, _, log_file = _build_workspace_and_step(tmp_path)
    updates = []

    class FakeSubFlow:
        def __init__(self, workspace, workspace_step):
            pass

        def update_step(self, step_name, state, runtime="", memory=0, info=None):
            updates.append((step_name, state))

    monkeypatch.setattr(runner, "YosysSubFlow", FakeSubFlow)
    monkeypatch.setattr(runner, "get_yosys_runtime", lambda: ([], {"PATH": "/tmp"}))

    result = runner.run_step(workspace=workspace, step=step)

    assert result is False
    assert ("run yosys", StateEnum.Invalid) in updates
    assert "yosys is not available" in log_file.read_text()
