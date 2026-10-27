import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _load_entrypoint_module():
    project_root = Path(__file__).parents[2]
    module_path = project_root / "packaging" / "run_ecc.py"
    spec = importlib.util.spec_from_file_location("ecc_packaged_entrypoint", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_worker_flag_selects_worker_entrypoint(monkeypatch):
    module = _load_entrypoint_module()
    calls = []

    monkeypatch.setattr(sys, "argv", [os.path.join("dist", "ecc"), "--ecc-candidate-worker"])
    monkeypatch.setattr("agent.candidate_worker.main", lambda: calls.append("worker") or 9)

    assert module.main() == 9
    assert calls == ["worker"]


def test_step_worker_flag_selects_worker_entrypoint(monkeypatch):
    module = _load_entrypoint_module()
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [os.path.join("dist", "ecc"), "--ecc-worker", "chipcompiler.engine.step_subprocess"],
    )
    monkeypatch.setattr(
        "chipcompiler.engine.step_subprocess.main", lambda: calls.append("worker") or 7
    )

    assert module.main() == 7
    assert calls == ["worker"]


@pytest.mark.parametrize("arguments", [["--ecc-worker"], ["--ecc-worker", "unknown.module"]])
def test_invalid_worker_dispatch_exits_nonzero_without_import(arguments):
    project_root = Path(__file__).parents[2]
    completed = subprocess.run(
        [sys.executable, str(project_root / "packaging" / "run_ecc.py"), *arguments],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "ModuleNotFoundError" not in completed.stderr


def test_packaged_entrypoint_propagates_exit_code():
    project_root = Path(__file__).parents[2]
    source = (project_root / "packaging" / "run_ecc.py").read_text()

    assert "raise SystemExit(main())" in source
