import os
import subprocess
import sys
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.commands import fe

_FAKE_ECC_FE = """#!/bin/sh
echo "program=$ECC_FE_PROGRAM"
for argument in "$@"; do echo "arg=$argument"; done
echo "to stderr" >&2
exit 3
"""


@pytest.fixture
def ecc_fe(tmp_path) -> Path:
    executable = tmp_path / "bin" / "ecc-fe"
    executable.parent.mkdir()
    executable.write_text(_FAKE_ECC_FE, encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _ecc(arguments: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "chipcompiler.cli.main", *arguments],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--help"],
        ["run", "--help"],
        ["--debug", "status", "--project", "a b", "--json"],
        ["runs", "delete", "--", "--odd-id"],
        ["param", "set", "lint.rules_off", '["WIDTH"]'],
    ],
    ids=lambda arguments: " ".join(arguments) or "no arguments",
)
def test_fe_hands_over_arguments_streams_and_exit_status(ecc_fe, arguments):
    env = {**os.environ, "PATH": f"{ecc_fe.parent}{os.pathsep}{os.environ['PATH']}"}
    env.pop(fe.ROOT_ENV, None)

    result = _ecc(["fe", *arguments], env)

    assert (result.returncode, result.stdout, result.stderr) == (
        3,
        "program=ecc fe\n" + "".join(f"arg={argument}\n" for argument in arguments),
        "to stderr\n",
    )


def test_fe_uses_the_installation_named_by_the_environment(ecc_fe, tmp_path):
    root = str(ecc_fe.parent.parent)
    env = {**os.environ, "PATH": str(tmp_path / "empty"), fe.ROOT_ENV: root}

    result = _ecc(["fe", "version"], env)

    assert (result.returncode, result.stdout) == (3, "program=ecc fe\narg=version\n")


def test_the_named_installation_comes_before_path(ecc_fe, tmp_path, monkeypatch):
    on_path = tmp_path / "other" / "ecc-fe"
    on_path.parent.mkdir()
    on_path.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    on_path.chmod(0o755)
    monkeypatch.setenv("PATH", str(on_path.parent))
    monkeypatch.setenv(fe.ROOT_ENV, str(ecc_fe.parent.parent))

    assert fe.find_ecc_fe() == str(ecc_fe)


@pytest.mark.parametrize("executable", [False, True], ids=["missing", "not executable"])
def test_a_root_without_the_executable_falls_back_to_path(
    ecc_fe, tmp_path, monkeypatch, executable
):
    root = tmp_path / "broken"
    (root / "bin").mkdir(parents=True)
    if executable:
        (root / "bin" / "ecc-fe").write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", str(ecc_fe.parent))
    monkeypatch.setenv(fe.ROOT_ENV, str(root))

    assert fe.find_ecc_fe() == str(ecc_fe)


def test_fe_reports_a_missing_frontend(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv(fe.ROOT_ENV, raising=False)

    assert cli_main.run(["fe", "run"]) == fe.EXIT_NOT_FOUND

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ecc: error: ecc-fe was not found; install ECC-FE and put `ecc-fe` on PATH, "
        "or set CHIPCOMPILER_ECC_FE_ROOT to its installation directory\n"
    )


def test_a_packaged_ecc_gives_the_frontend_the_original_loader_path(ecc_fe, monkeypatch):
    handed_over = {}

    def execve(_path, _arguments, env):
        handed_over.update(env)
        raise SystemExit(0)

    monkeypatch.setattr(fe.os, "execve", execve)
    monkeypatch.setattr(fe.sys, "frozen", True, raising=False)
    monkeypatch.setenv(fe.ROOT_ENV, str(ecc_fe.parent.parent))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/host/lib")

    cli_main.run(["fe", "version"])

    assert handed_over["LD_LIBRARY_PATH"] == "/host/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in handed_over
