#!/usr/bin/env python
import os
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.yosys import utility


def _create_oss_cad_tree(base_dir: Path) -> tuple[Path, Path]:
    """Create a minimal OSS CAD directory layout for testing."""
    oss_path = base_dir / "oss-cad-suite"
    bin_dir = oss_path / "bin"
    bin_dir.mkdir(parents=True)

    yosys_name = "yosys.exe" if utility.os.name == "nt" else "yosys"
    yosys_bin = bin_dir / yosys_name
    yosys_bin.write_text("")

    share_dir = oss_path / "share" / "yosys"
    (share_dir / "plugins").mkdir(parents=True)
    (share_dir / "techlibs").mkdir(parents=True)

    return oss_path, yosys_bin


def test_get_yosys_command_prefers_oss_cad_without_mutating_environ(tmp_path, monkeypatch):
    oss_path, yosys_bin = _create_oss_cad_tree(tmp_path)

    monkeypatch.setenv("CHIPCOMPILER_OSS_CAD_DIR", str(oss_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("YOSYS_PLUGINPATH", raising=False)
    monkeypatch.delenv("YOSYS_DATDIR", raising=False)

    before = {k: os.environ.get(k) for k in ["PATH", "YOSYS_PLUGINPATH", "YOSYS_DATDIR"]}
    command = utility.get_yosys_command()
    after = {k: os.environ.get(k) for k in ["PATH", "YOSYS_PLUGINPATH", "YOSYS_DATDIR"]}

    assert command == [str(yosys_bin)]
    assert before == after


def test_get_yosys_command_returns_empty_when_not_found(monkeypatch):
    monkeypatch.delenv("CHIPCOMPILER_OSS_CAD_DIR", raising=False)
    monkeypatch.setattr(utility.shutil, "which", lambda _: None)

    assert utility.get_yosys_command() == []


def test_get_yosys_runtime_builds_local_env_without_mutating_global_env(tmp_path, monkeypatch):
    oss_path, yosys_bin = _create_oss_cad_tree(tmp_path)

    monkeypatch.setenv("CHIPCOMPILER_OSS_CAD_DIR", str(oss_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("YOSYS_PLUGINPATH", raising=False)
    monkeypatch.delenv("YOSYS_DATDIR", raising=False)

    before = {k: os.environ.get(k) for k in ["PATH", "YOSYS_PLUGINPATH", "YOSYS_DATDIR"]}
    command, env = utility.get_yosys_runtime()
    after = {k: os.environ.get(k) for k in ["PATH", "YOSYS_PLUGINPATH", "YOSYS_DATDIR"]}

    expected_prefix = str(oss_path / "bin") + os.pathsep
    assert command == [str(yosys_bin)]
    assert env["PATH"].startswith(expected_prefix)
    assert env["YOSYS_PLUGINPATH"] == str(oss_path / "share" / "yosys" / "plugins")
    assert env["YOSYS_DATDIR"] == str(oss_path / "share" / "yosys")
    assert before == after


def test_check_slang_plugin_executes_expected_command(tmp_path, monkeypatch):
    log_path = tmp_path / "check.log"
    calls = []

    def fake_run(cmd, cwd, env, stdout, stderr, timeout):
        calls.append({
            "cmd": list(cmd),
            "cwd": cwd,
            "env": env,
            "timeout": timeout,
        })
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(utility.subprocess, "run", fake_run)
    with open(log_path, "w") as log_file:
        ok = utility.check_slang_plugin(
            yosys_cmd=["yosys"],
            cwd_dir="/tmp/test",
            yosys_env={"PATH": "/tmp/bin"},
            log_file=log_file
        )

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["cmd"] == ["yosys", "-p", "plugin -i slang"]
    assert calls[0]["cwd"] == "/tmp/test"
    assert calls[0]["env"] == {"PATH": "/tmp/bin"}
    assert calls[0]["timeout"] == 60


def test_check_slang_plugin_writes_error_on_failure(tmp_path, monkeypatch):
    log_path = tmp_path / "check_fail.log"

    def fake_run(cmd, cwd, env, stdout, stderr, timeout):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(utility.subprocess, "run", fake_run)
    with open(log_path, "w") as log_file:
        ok = utility.check_slang_plugin(
            yosys_cmd=["yosys"],
            cwd_dir="/tmp/test",
            yosys_env={"PATH": "/tmp/bin"},
            log_file=log_file
        )

    assert ok is False
    assert "slang plugin check failed" in log_path.read_text()
