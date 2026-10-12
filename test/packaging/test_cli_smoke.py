import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def _load_smoke_module():
    path = Path(__file__).parents[2] / "packaging" / "cli_smoke.py"
    spec = importlib.util.spec_from_file_location("ecc_cli_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_smoke = _load_smoke_module().run_smoke


def test_smoke_invokes_json_commands_in_contract_order(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = json.dumps([{"status": "pass"}])
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    binary = tmp_path / "ecc"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", fake_run)

    reports = run_smoke(binary, tmp_path, "default")

    assert [report["command"] for report in reports] == [
        "status",
        "step report",
        "project report",
        "signoff check",
        "pdk verify",
    ]
    assert calls[0][-1] == "--json"
    assert all("--project" in call for call in calls)
    assert "--workspace" in calls[0]
    assert "--workspace" not in calls[2]
    assert "--workspace" not in calls[4]


def test_smoke_preserves_nonzero_quality_gate_code(monkeypatch, tmp_path):
    class Result:
        returncode = 6
        stdout = json.dumps([{"signoff": "check", "status": "fail"}])
        stderr = ""

    binary = tmp_path / "ecc"
    binary.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())

    reports = run_smoke(binary, tmp_path, None)

    assert all(report["exit_code"] == 6 for report in reports)


def test_smoke_rejects_non_json_output(monkeypatch, tmp_path):
    class Result:
        returncode = 0
        stdout = "not json"
        stderr = ""

    binary = tmp_path / "ecc"
    binary.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(RuntimeError, match="did not emit JSON"):
        run_smoke(binary, tmp_path, None)
